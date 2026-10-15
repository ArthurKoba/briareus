import {readBoundedJsonResponse,readBoundedErrorCode} from "@/shared/lib/bounded-json-response"
import {CONTROL_PANEL_API_V1} from "@/shared/config/control-panel-api"
/** Source-only peer Backend contract:
 * services/api/src/control_panel_api/_oidc_approvals.py (LOCAL, not released).
 * The owner independently authorizes Project scope and writes. This client
 * never turns a Rauthy identity or displayed allowed_actions into a Permit.
 */
import type { ElevationPolicy } from "./open-normal"
import { parseHandEffectScopes, type HandEffectScope } from "@/shared/lib/hand-effect-scope"

const UUID4=/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/
const OPERATIONS=new Set([
  "files.read","files.write","project.metadata.read","terminal.execute",
  "web.access","analysis.import","agents.manage","integrations.use",
  "variables.use","integrations.manage","variables.manage",
])
const ISO_WITH_OFFSET=/(?:Z|[+-][0-2][0-9]:[0-5][0-9])$/
const MAX_ITEMS=50

export type SessionStatus="active"|"expired"|"revoked"
export type SessionScope=HandEffectScope
export interface CurrentAgentSession {
  session_uuid:string
  project_uuid:string
  created_by_user_uuid:string
  revision:number
  status:SessionStatus
  is_elevated:boolean
  elevation_policy:ElevationPolicy
  hard_expires_at:string
  operations:string[]
  resources:SessionScope[]
  allowed_actions:("revoke")[]
}
export type SessionInventory=
  | {kind:"ready";items:CurrentAgentSession[]}
  | {kind:"unauthorized"|"forbidden"|"conflict"|"invalid"|"unavailable";code:string}
export type CurrentSessionRead=
  | {kind:"ready";item:CurrentAgentSession}
  | {kind:"not_found";code:"AGENT_SESSION_NOT_FOUND"}
  | {kind:"unauthorized"|"forbidden"|"conflict"|"invalid"|"unavailable";code:string}
export type SessionRevokeResult=
  | {kind:"confirmed";session_uuid:string;project_uuid:string;revision:number}
  | {kind:"unauthorized"|"forbidden"|"conflict"|"invalid"|"unavailable"|"uncertain";code:string}

function obj(value:unknown):Record<string,unknown>|null{
  return value!==null&&typeof value==="object"&&!Array.isArray(value)
    ?value as Record<string,unknown>:null
}
export function isCurrentSessionId(value:unknown):value is string{return typeof value==="string"&&UUID4.test(value)}
const uuid=isCurrentSessionId
function validTime(value:unknown):value is string{
  return typeof value==="string"&&ISO_WITH_OFFSET.test(value)&&Number.isFinite(Date.parse(value))
}
export function parseCurrentSession(
  value:unknown,
  projectUuid:string,
  actorUuid:string,
  canApprove:boolean,
  now=Date.now(),
):CurrentAgentSession|null {
  const v=obj(value)
  if(!v||!uuid(v.session_uuid)||v.project_uuid!==projectUuid||
    !uuid(v.created_by_user_uuid)||
    (!canApprove&&v.created_by_user_uuid!==actorUuid)||
    !Number.isSafeInteger(v.revision)||(v.revision as number)<1||
    !["active","revoked","expired"].includes(String(v.status))||
    typeof v.is_elevated!=="boolean"||
    (v.elevation_policy!=="fixed"&&v.elevation_policy!=="requestable")||
    !validTime(v.hard_expires_at)||
    (v.status==="active"&&Date.parse(v.hard_expires_at)<=now)||
    (v.status==="expired"&&Date.parse(v.hard_expires_at)>now)||
    !Array.isArray(v.operations)||v.operations.length<1||v.operations.length>32||
    v.operations.some(x=>typeof x!=="string"||!OPERATIONS.has(x))||
    new Set(v.operations).size!==v.operations.length||
    !Array.isArray(v.resources)||v.resources.length>32||
    !Array.isArray(v.allowed_actions)||v.allowed_actions.length>1||
    (v.allowed_actions.length===1&&v.allowed_actions[0]!=="revoke")||
    (v.allowed_actions.length>0&&
      (!canApprove||v.status!=="active"||Date.parse(v.hard_expires_at)<=now)))return null
  const resources=parseHandEffectScopes(v.resources,v.operations,projectUuid)
  if(!resources)return null
  return {
    session_uuid:v.session_uuid,project_uuid:projectUuid,
    created_by_user_uuid:v.created_by_user_uuid,
    revision:v.revision as number,status:v.status as SessionStatus,
    is_elevated:v.is_elevated,
    elevation_policy:v.elevation_policy,
    hard_expires_at:v.hard_expires_at,
    operations:[...v.operations] as string[],
    resources,allowed_actions:[...v.allowed_actions] as ("revoke")[],
  }
}
function fail(status:number,code:string):Exclude<SessionInventory,{kind:"ready"}>{
  return {kind:status===401?"unauthorized":status===403?"forbidden":
    status===409?"conflict":status===422?"invalid":"unavailable",code}
}
function readRequest(signal:AbortSignal):RequestInit {
  return {method:"GET",signal,credentials:"same-origin",mode:"same-origin",
    redirect:"error",cache:"no-store",referrerPolicy:"no-referrer",
    headers:{Accept:"application/json"}}
}
/** Backend uses the same owner and projection validation as inventory.
 * A missing record/route or invalid response is not proof of revocation.
 */
export async function readCurrentSession(
  projectUuid:string,sessionUuid:string,actorUuid:string,canApprove:boolean,
  signal:AbortSignal,
):Promise<CurrentSessionRead>{
  if(!uuid(projectUuid)||!uuid(sessionUuid)||!uuid(actorUuid))return {kind:"invalid",code:"INVALID_SCOPE"}
  if(signal.aborted)return {kind:"unavailable",code:"AGENT_SESSION_READ_CANCELLED"}
  try{
    const response=await fetch(CONTROL_PANEL_API_V1+"/agent-sessions/"+sessionUuid+
      "?project_uuid="+projectUuid,readRequest(signal))
    if(signal.aborted)return {kind:"unavailable",code:"AGENT_SESSION_READ_CANCELLED"}
    if(response.status!==200){
      const code=await readBoundedErrorCode(response,signal,"UNKNOWN")
      if(signal.aborted)return {kind:"unavailable",code:"AGENT_SESSION_READ_CANCELLED"}
      if(response.status===404&&code==="AGENT_SESSION_NOT_FOUND")return {kind:"not_found",code}
      return fail(response.status,code)
    }
    const item=parseCurrentSession(await readBoundedJsonResponse(response,signal,131_072),projectUuid,actorUuid,canApprove)
    if(signal.aborted)return {kind:"unavailable",code:"AGENT_SESSION_READ_CANCELLED"}
    if(!item||item.session_uuid!==sessionUuid)return {kind:"invalid",code:"AGENT_SESSION_DTO_INVALID"}
    return {kind:"ready",item}
  }catch{return {kind:"unavailable",code:signal.aborted?"AGENT_SESSION_READ_CANCELLED":"AGENT_SESSION_READ_UNAVAILABLE"}}
}
export async function listCurrentSessions(
  projectUuid:string,
  actorUuid:string,
  canApprove:boolean,
  signal:AbortSignal,
):Promise<SessionInventory>{
  if(!uuid(projectUuid)||!uuid(actorUuid))return {kind:"invalid",code:"INVALID_SCOPE"}
  if(signal.aborted)return {kind:"unavailable",code:"AGENT_SESSION_LIST_CANCELLED"}
  try{
    const response=await fetch(CONTROL_PANEL_API_V1+"/agent-sessions?project_uuid="+projectUuid,readRequest(signal))
    if(signal.aborted)return {kind:"unavailable",code:"AGENT_SESSION_LIST_CANCELLED"}
    if(response.status!==200){
      const code=await readBoundedErrorCode(response,signal,"UNKNOWN")
      if(signal.aborted)return {kind:"unavailable",code:"AGENT_SESSION_LIST_CANCELLED"}
      return fail(response.status,code)
    }
    const data=obj(await readBoundedJsonResponse(response,signal,6_291_456))
    if(signal.aborted)return {kind:"unavailable",code:"AGENT_SESSION_LIST_CANCELLED"}
    if(!data||!Array.isArray(data.items)||data.items.length>MAX_ITEMS)
      return {kind:"invalid",code:"AGENT_SESSION_DTO_INVALID"}
    const seen=new Set<string>(),items:CurrentAgentSession[]=[]
    for(const row of data.items){
      const parsed=parseCurrentSession(row,projectUuid,actorUuid,canApprove)
      if(!parsed||seen.has(parsed.session_uuid))
        return {kind:"invalid",code:"AGENT_SESSION_DTO_INVALID"}
      seen.add(parsed.session_uuid)
      items.push(parsed)
    }
    if(signal.aborted)return {kind:"unavailable",code:"AGENT_SESSION_LIST_CANCELLED"}
    return {kind:"ready",items}
  }catch{
    return {kind:"unavailable",code:signal.aborted?"AGENT_SESSION_LIST_CANCELLED":"AGENT_SESSION_LIST_UNAVAILABLE"}
  }
}
/** A version-fenced server-side revocation; caller must revalidate the
 * independent current approver privilege immediately before invoking this.
 * HTTP 200 is provisional until caller reads the exact current session.
 */
export async function revokeCurrentSession(
  session:CurrentAgentSession,
  signal:AbortSignal,
):Promise<SessionRevokeResult>{
  if(signal.aborted)return {kind:"unavailable",code:"REVOKE_CANCELLED_BEFORE_DISPATCH"}
  const project=session.project_uuid,id=session.session_uuid,revision=session.revision
  if(!uuid(project)||!uuid(id)||
    session.status!=="active"||!session.allowed_actions.includes("revoke")||
    !Number.isSafeInteger(session.revision)||session.revision<1||
    Date.parse(session.hard_expires_at)<=Date.now())
    return {kind:"invalid",code:"REVOKE_NOT_ALLOWED"}
  if(typeof crypto==="undefined"||typeof crypto.randomUUID!=="function")
    return {kind:"unavailable",code:"SECURE_CONTEXT_REQUIRED"}
  const operation=crypto.randomUUID()
  try{
    const response=await fetch(CONTROL_PANEL_API_V1+"/agent-sessions/"+id+"/revoke",{
      method:"POST",signal,credentials:"same-origin",mode:"same-origin",
      redirect:"error",cache:"no-store",referrerPolicy:"no-referrer",
      headers:{Accept:"application/json","Content-Type":"application/json",
        "Operation-UUID":operation,"Idempotency-Key":operation},
      body:JSON.stringify({
        project_uuid:project,expected_grant_revision:revision,
      }),
    })
    if(signal.aborted)return {kind:"uncertain",code:"REVOKE_RESULT_UNCERTAIN"}
    if(response.status!==200){
      const code=await readBoundedErrorCode(response,signal,"UNKNOWN")
      if(signal.aborted)return {kind:"uncertain",code:"REVOKE_RESULT_UNCERTAIN"}
      const result=fail(response.status,code)
      return {kind:result.kind,code:result.code}
    }
    const result=obj(await readBoundedJsonResponse(response,signal,16_384))
    if(signal.aborted)return {kind:"uncertain",code:"REVOKE_RESULT_UNCERTAIN"}
    if(!result||result.session_uuid!==id||
      result.project_uuid!==project||result.status!=="revoked"||
      !Number.isSafeInteger(result.revision)||
      (result.revision as number)<=revision)return {kind:"uncertain",code:"REVOKE_RESULT_UNVERIFIED"}
    return {kind:"confirmed",session_uuid:id,
      project_uuid:project,revision:result.revision as number}
  }catch{
    return {kind:"uncertain",code:"REVOKE_RESULT_UNCERTAIN"}
  }
}
