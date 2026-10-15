import {CONTROL_PANEL_API_V1} from "@/shared/config/control-panel-api"
import {
  parseHandEffectScopes, hasCompleteHandScopeCoverage, type HandEffectScope,
} from "@/shared/lib/hand-effect-scope"

/** SOURCE contract: Backend services/api/src/control_panel_api/_oidc_approvals.py.
 * This Control Panel API is cookie-bound and defaults to 503 until the real
 * Authorization/Platform owner adapter is installed. Never mint grants in UI.
 */
export type ApprovalStatus = "pending" | "approved" | "rejected"
export type ApprovalAction = "approve" | "deny"

export type ScopedEffect=HandEffectScope
export interface ApprovalRecord {
  id:string
  project_uuid:string
  agent_session_uuid:string
  requested_by_user_uuid:string
  status:ApprovalStatus
  version:number
  requested_operations:string[]
  requested_resources:ScopedEffect[]
  requested_expires_at:string
  resolved_by_user_uuid:string|null
  issued_session_uuid:string|null
  allowed_actions:ApprovalAction[]
}
export type ApprovalResult =
  | {kind:"ready";items:ApprovalRecord[]}
  | {kind:"unauthorized"|"forbidden"|"conflict"|"invalid"|"unavailable";code:string}

export type ApprovalResolution =
  | {kind:"confirmed";item:ApprovalRecord}
  | {kind:"unauthorized"|"forbidden"|"conflict"|"invalid"|"unavailable"|"uncertain";code:string}

const UUID4=/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/
const ALLOWED_OPERATIONS=new Set([
  "files.read","files.write","project.metadata.read","terminal.execute",
  "web.access","analysis.import","agents.manage","integrations.use",
  "variables.use","integrations.manage","variables.manage",
])
function record(value:unknown):Record<string,unknown>|null{
  return value!==null&&typeof value==="object"&&!Array.isArray(value)?value as Record<string,unknown>:null
}
function uuid(value:unknown):value is string{return typeof value==="string"&&UUID4.test(value)}
function freshIso(value:unknown):value is string{
  return typeof value==="string"&&
    /(?:Z|[+-][0-2][0-9]:[0-5][0-9])$/.test(value)&&Number.isFinite(Date.parse(value))
}
export function parseApproval(value:unknown,projectUuid:string):ApprovalRecord|null{
  const r=record(value)
  if(!r||!uuid(r.id)||r.project_uuid!==projectUuid||!uuid(r.agent_session_uuid)||
    !uuid(r.requested_by_user_uuid)||!["pending","approved","rejected"].includes(String(r.status))||
    !Number.isSafeInteger(r.version)||(r.version as number)<1||
    !freshIso(r.requested_expires_at)||
    !Array.isArray(r.requested_operations)||r.requested_operations.length<1||r.requested_operations.length>32||
    r.requested_operations.some(x=>typeof x!=="string"||!ALLOWED_OPERATIONS.has(x))||
    new Set(r.requested_operations).size!==r.requested_operations.length||
    !Array.isArray(r.requested_resources)||r.requested_resources.length>32||
    (r.resolved_by_user_uuid!==null&&!uuid(r.resolved_by_user_uuid))||
    (r.issued_session_uuid!==null&&!uuid(r.issued_session_uuid))||
    !Array.isArray(r.allowed_actions)||r.allowed_actions.length>2||
    r.allowed_actions.some(x=>x!=="approve"&&x!=="deny")||
    new Set(r.allowed_actions).size!==r.allowed_actions.length)return null
  if(r.status==="pending"){
    if(r.resolved_by_user_uuid!==null||r.issued_session_uuid!==null)return null
  }else if(r.resolved_by_user_uuid===null||r.resolved_by_user_uuid===r.requested_by_user_uuid||
    (r.status==="approved")!==(r.issued_session_uuid!==null)||
    r.issued_session_uuid===r.agent_session_uuid)return null
  const resources=parseHandEffectScopes(r.requested_resources,r.requested_operations,projectUuid)
  if(!resources)return null
  // The new Access command contract rejects action-only elevation. A
  // pending approval without exact scope coverage cannot be approved.
  if(r.status==="pending"&&!hasCompleteHandScopeCoverage(r.requested_operations,resources))return null
  // A final resolved or already-expired request cannot have live owner actions.
  if((r.status!=="pending"||Date.parse(r.requested_expires_at)<=Date.now())&&r.allowed_actions.length!==0)return null
  return {
    id:r.id,project_uuid:projectUuid,agent_session_uuid:r.agent_session_uuid,
    requested_by_user_uuid:r.requested_by_user_uuid,status:r.status as ApprovalStatus,
    version:r.version as number,requested_operations:[...r.requested_operations],
    requested_resources:resources,requested_expires_at:r.requested_expires_at,
    resolved_by_user_uuid:r.resolved_by_user_uuid,
    issued_session_uuid:r.issued_session_uuid,
    allowed_actions:[...r.allowed_actions] as ApprovalAction[],
  }
}
/** These fields describe the user's original requested effect, not the
 * resolution. Reordering is allowed; resource substitution is not. */
export function sameRequestedEffect(a:ApprovalRecord,b:ApprovalRecord):boolean {
  const scopes=(row:ApprovalRecord)=>row.requested_resources.map(scope=>JSON.stringify([
    scope.hand,scope.tool,scope.action,scope.resource.kind,scope.resource.id,
  ])).sort()
  return a.project_uuid===b.project_uuid&&a.agent_session_uuid===b.agent_session_uuid&&
    a.requested_by_user_uuid===b.requested_by_user_uuid&&
    Date.parse(a.requested_expires_at)===Date.parse(b.requested_expires_at)&&
    JSON.stringify([...a.requested_operations].sort())===JSON.stringify([...b.requested_operations].sort())&&
    JSON.stringify(scopes(a))===JSON.stringify(scopes(b))
}
/** UI-only stale-dialog guard. A fresh server proof is still required and
 * Backend owns the actual Cedar decision. Prevents a dialog opened for the
 * previous selected Project/actor or revision from issuing a write later.
 */
export function approvalStillCurrentForActor(
  selected:ApprovalRecord,
  currentRows:readonly ApprovalRecord[],
  action:ApprovalAction,
  projectUuid:string,
  actorUuid:string,
  now=Date.now(),
):boolean {
  const fresh=currentRows.find(row=>row.id===selected.id)
  return !!fresh&&selected.project_uuid===projectUuid&&
    fresh.project_uuid===projectUuid&&fresh.version===selected.version&&
    sameRequestedEffect(fresh,selected)&&
    fresh.status==="pending"&&fresh.allowed_actions.includes(action)&&
    Date.parse(fresh.requested_expires_at)>now&&
    fresh.requested_by_user_uuid!==actorUuid
}
function transport(signal:AbortSignal):RequestInit{
  return {signal,credentials:"same-origin",mode:"same-origin",redirect:"error",
    referrerPolicy:"no-referrer",cache:"no-store",headers:{Accept:"application/json"}}
}
async function serverCode(response:Response):Promise<string>{
  try{
    const body=record(await response.json()),error=record(body?.error)
    return typeof error?.code==="string"&&error.code.length<=128?error.code:"UNKNOWN"
  }catch{return "UNKNOWN"}
}
function failure(status:number,code:string):Exclude<ApprovalResult,{kind:"ready"}>{
  return {kind:status===401?"unauthorized":status===403?"forbidden":status===409?"conflict":
    status===422?"invalid":"unavailable",code}
}
export async function readProjectApprovals(projectUuid:string,signal:AbortSignal):Promise<ApprovalResult>{
  if(!uuid(projectUuid))return {kind:"invalid",code:"INVALID_PROJECT_UUID"}
  if(signal.aborted)return {kind:"unavailable",code:"APPROVAL_READ_CANCELLED"}
  try{
    const response=await fetch(CONTROL_PANEL_API_V1+"/approvals?project_uuid="+encodeURIComponent(projectUuid),transport(signal))
    if(signal.aborted)return {kind:"unavailable",code:"APPROVAL_READ_CANCELLED"}
    if(response.status!==200)return failure(response.status,await serverCode(response))
    const body=record(await response.json())
    if(signal.aborted)return {kind:"unavailable",code:"APPROVAL_READ_CANCELLED"}
    if(!body||!Array.isArray(body.items)||body.items.length>50)return {kind:"invalid",code:"APPROVAL_DTO_INVALID"}
    const ids=new Set<string>(),items:ApprovalRecord[]=[]
    for(const raw of body.items){
      const row=parseApproval(raw,projectUuid)
      if(!row||ids.has(row.id))return {kind:"invalid",code:"APPROVAL_DTO_INVALID"}
      ids.add(row.id)
      items.push(row)
    }
    return {kind:"ready",items}
  }catch{return {kind:"unavailable",code:"APPROVAL_NETWORK_UNAVAILABLE"}}
}
/** The server owns the write and its idempotency. No UI optimistic approval. */
export async function resolveProjectApproval(
  item:ApprovalRecord,
  action:ApprovalAction,
  signal:AbortSignal,
):Promise<ApprovalResolution>{
  if(signal.aborted)return {kind:"unavailable",code:"APPROVAL_CANCELLED_BEFORE_DISPATCH"}
  if(!uuid(item.id)||!uuid(item.project_uuid)||item.status!=="pending"||
    !item.allowed_actions.includes(action)||!Number.isSafeInteger(item.version)||
    Date.parse(item.requested_expires_at)<=Date.now())return {kind:"invalid",code:"APPROVAL_ACTION_NOT_ALLOWED"}
  // Must run only in a browser secure context with real UUIDv4 crypto.
  if(typeof crypto==="undefined"||typeof crypto.randomUUID!=="function"){
    return {kind:"unavailable",code:"SECURE_CONTEXT_REQUIRED"}
  }
  const operation=crypto.randomUUID()
  try{
    const response=await fetch(CONTROL_PANEL_API_V1+"/approvals/"+item.id+"/resolve",{
      ...transport(signal),method:"POST",
      headers:{Accept:"application/json","Content-Type":"application/json",
        "Operation-UUID":operation,"Idempotency-Key":operation},
      body:JSON.stringify({project_uuid:item.project_uuid,approve:action==="approve",
        expected_approval_version:item.version}),
    })
    if(signal.aborted)return {kind:"uncertain",code:"APPROVAL_RESULT_UNCERTAIN"}
    if(response.status!==200){
      const fail=failure(response.status,await serverCode(response))
      return {kind:fail.kind,code:fail.code}
    }
    const row=parseApproval(await response.json(),item.project_uuid)
    if(signal.aborted)return {kind:"uncertain",code:"APPROVAL_RESULT_UNCERTAIN"}
    if(!row||row.id!==item.id||row.version!==item.version+1||
      !sameRequestedEffect(row,item)||
      row.status!==(action==="approve"?"approved":"rejected")||
      row.allowed_actions.length!==0)return {kind:"uncertain",code:"APPROVAL_RESULT_NOT_VERIFIED"}
    return {kind:"confirmed",item:row}
  }catch{return {kind:"uncertain",code:"APPROVAL_RESULT_UNCERTAIN"}}
}
