import {CONTROL_PANEL_API_V1} from "@/shared/config/control-panel-api"
import {boundedLifetime,type BoundedLifetime} from "@/shared/lib/bounded-lifetime"

/** Source: Backend services/api/src/control_panel_api/_oidc_approvals.py
 * POST /api/v1/agent-sessions (local source only, owner default 503).
 * A verified 201 establishes only this returned normal session. Current
 * inventory is read independently; this response is not elevated permission.
 */
export type ElevationPolicy = "fixed" | "requestable"
export interface NormalSession {
  session_uuid: string
  project_uuid: string
  revision: 1
  status: "active"
  is_elevated: false
  elevation_policy: ElevationPolicy
  hard_expires_at: string
  operations: ["files.read", "project.metadata.read"]
  resources: []
}
export type NormalSessionResult =
  | {kind:"created";session:NormalSession}
  | {kind:"unauthorized"|"forbidden"|"conflict"|"invalid"|"unavailable"|"uncertain";code:string}
const UUID4=/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/
const MAX_AGE_MS=24*60*60*1000
function object(value:unknown):Record<string,unknown>|null{
  return typeof value==="object"&&value!==null&&!Array.isArray(value)
    ?value as Record<string,unknown>:null
}
export function parseNormalSession(value:unknown,project:string,policy:ElevationPolicy,now=Date.now()):NormalSession|null{
  const r=object(value)
  if(!r||typeof r.session_uuid!=="string"||!UUID4.test(r.session_uuid)||
    r.project_uuid!==project||r.revision!==1||r.status!=="active"||
    r.is_elevated!==false||r.elevation_policy!==policy||
    typeof r.hard_expires_at!=="string"||
    !/(?:Z|[+-][0-2][0-9]:[0-5][0-9])$/.test(r.hard_expires_at)||
    !Number.isFinite(Date.parse(r.hard_expires_at))||
    Date.parse(r.hard_expires_at)<=now||Date.parse(r.hard_expires_at)>now+MAX_AGE_MS+1000||
    !Array.isArray(r.operations)||r.operations.length!==2||
    r.operations[0]!=="files.read"||r.operations[1]!=="project.metadata.read"||
    !Array.isArray(r.resources)||r.resources.length!==0)return null
  return {
    session_uuid:r.session_uuid,project_uuid:project,revision:1,status:"active",
    is_elevated:false,elevation_policy:policy,hard_expires_at:r.hard_expires_at,
    operations:["files.read","project.metadata.read"],resources:[],
  }
}
async function errorCode(response:Response):Promise<string>{
  try{
    const value=object(await response.json()), error=object(value?.error)
    return typeof error?.code==="string"&&error.code.length<=128?error.code:"UNKNOWN"
  }catch{return "UNKNOWN"}
}
/** An immutable request intent, kept in memory until its outcome is known.
 * Replays reuse these exact serialized bytes and the original operation UUID.
 */
export interface PreparedNormalSessionOpen {
  readonly project:string
  readonly policy:ElevationPolicy
  readonly label:string
  readonly operation:string
  readonly body:string
}
export type SessionOpenPreparation=
  | {kind:"prepared";command:PreparedNormalSessionOpen}
  | {kind:"invalid"|"unavailable";code:string}
// Stop replay after the normal session's 24h lifetime, well before Access's
// seven-day idempotency retention. Never reuse an indefinitely old key after
// its owner may legitimately have removed the deduplication record.
const preparedCommands=new WeakMap<object,BoundedLifetime>()
export function prepareNormalSessionOpen(project:string,policy:ElevationPolicy,label:string):SessionOpenPreparation {
  if(!UUID4.test(project)||!["fixed","requestable"].includes(policy)||
    label.length>128||label.trim()!==label||[...label].some(c=>c.charCodeAt(0)<32||c.charCodeAt(0)===127))
    return {kind:"invalid",code:"AGENT_SESSION_INPUT_INVALID"}
  if(typeof crypto==="undefined"||typeof crypto.randomUUID!=="function")
    return {kind:"unavailable",code:"SECURE_CONTEXT_REQUIRED"}
  const command=Object.freeze({project,policy,label,operation:crypto.randomUUID(),
    body:JSON.stringify({project_uuid:project,elevation_policy:policy,label:label.length>0?label:null}),
  })
  preparedCommands.set(command,boundedLifetime(Date.now()+MAX_AGE_MS))
  return {kind:"prepared",command}
}
/** Caller revalidates current User/Project before every explicitly requested
 * execution, including a replay. No automatic retry or permission cache. */
export function normalSessionReplayRemaining(command:PreparedNormalSessionOpen):number {
  return preparedCommands.get(command)?.remainingMilliseconds()??0
}
export async function executeNormalSessionOpen(
  command:PreparedNormalSessionOpen,signal:AbortSignal,
):Promise<NormalSessionResult>{
  const replayUntil=preparedCommands.get(command)
  if(replayUntil===undefined)return {kind:"invalid",code:"SESSION_COMMAND_NOT_PREPARED"}
  if(replayUntil.remainingMilliseconds()<=0)return {kind:"unavailable",code:"SESSION_RECOVERY_WINDOW_ELAPSED"}
  if(signal.aborted)return {kind:"unavailable",code:"SESSION_COMMAND_CANCELLED"}
  const {project,policy,operation,body}=command
  try{
    const response=await fetch(CONTROL_PANEL_API_V1+"/agent-sessions",{
      method:"POST",credentials:"same-origin",mode:"same-origin",redirect:"error",
      referrerPolicy:"no-referrer",cache:"no-store",signal,
      headers:{Accept:"application/json","Content-Type":"application/json",
        "Operation-UUID":operation,"Idempotency-Key":operation},body,
    })
    if(signal.aborted)return {kind:"uncertain",code:"SESSION_OPEN_OUTCOME_UNCERTAIN"}
    if(response.status===201){
      const record=parseNormalSession(await response.json(),project,policy)
      if(signal.aborted)return {kind:"uncertain",code:"SESSION_OPEN_OUTCOME_UNCERTAIN"}
      return record?{kind:"created",session:record}:{kind:"uncertain",code:"SESSION_RESULT_NOT_VERIFIED"}
    }
    const code=await errorCode(response)
    return {kind:response.status===401?"unauthorized":response.status===403?"forbidden":
      response.status===409?"conflict":response.status===422?"invalid":"uncertain",code}
  }catch{return {kind:"uncertain",code:"SESSION_OPEN_OUTCOME_UNCERTAIN"}}
}
/** One-shot compatibility API. Interactive UI retains a prepared command so
 * an uncertain result can be reconciled without a second creation intent. */
export async function openNormalSession(
  project:string,policy:ElevationPolicy,label:string,signal:AbortSignal,
):Promise<NormalSessionResult>{
  const prepared=prepareNormalSessionOpen(project,policy,label)
  return prepared.kind==="prepared"?executeNormalSessionOpen(prepared.command,signal):prepared
}
