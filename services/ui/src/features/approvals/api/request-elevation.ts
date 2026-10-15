import {CONTROL_PANEL_API_V1} from "@/shared/config/control-panel-api"
import { parseApproval, type ApprovalRecord } from "./control-panel"
import { parseHandEffectScopes, hasCompleteHandScopeCoverage, type HandEffectScope } from "@/shared/lib/hand-effect-scope"

/** A projection of a current owner-supplied AgentSession, not local authority. */
export interface ElevationTarget {
  project_uuid:string
  session_uuid:string
  revision:number
  status:"active"|"expired"|"revoked"
  elevation_policy:"fixed"|"requestable"
  hard_expires_at:string
}
export type ElevationRequestResult=
  | {kind:"pending";item:ApprovalRecord}
  | {kind:"unauthorized"|"forbidden"|"conflict"|"invalid"|"unavailable"|"uncertain";code:string}
const UUID=/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/
const scopeKey=(scope:HandEffectScope)=>JSON.stringify([scope.hand,scope.tool,scope.action,scope.resource.kind,scope.resource.id])

/** SOURCE contract: Backend POST /api/v1/approvals, RequestElevation.
 * Not mounted in UI until the real resource picker and fresh User/Project
 * checks are available. Caller supplies only owner-confirmed resource scope.
 * 202 creates a pending request, NEVER an elevated session or Cedar Permit.
 */
export async function requestSessionElevation(
  target:ElevationTarget,
  requestedResources:readonly HandEffectScope[],
  seconds:number,
  actorUuid:string,
  signal:AbortSignal,
):Promise<ElevationRequestResult>{
  if(signal.aborted)return {kind:"unavailable",code:"APPROVAL_REQUEST_CANCELLED"}
  const project=target.project_uuid,session=target.session_uuid,revision=target.revision
  if(!UUID.test(project)||!UUID.test(session)||!UUID.test(actorUuid)||
    target.status!=="active"||target.elevation_policy!=="requestable"||
    !Number.isSafeInteger(revision)||revision<1||!Number.isInteger(seconds)||seconds<1||seconds>300||
    !/(?:Z|[+-][0-2][0-9]:[0-5][0-9])$/.test(target.hard_expires_at)||
    !Number.isFinite(Date.parse(target.hard_expires_at))||Date.parse(target.hard_expires_at)<=Date.now()||
    !Array.isArray(requestedResources)||requestedResources.length<1||requestedResources.length>32){
    return {kind:"invalid",code:"ELEVATION_REQUEST_INVALID"}
  }
  const operations=[...new Set(requestedResources.map(scope=>scope?.action))]
  const resources=parseHandEffectScopes(requestedResources,operations,project)
  if(!resources||!hasCompleteHandScopeCoverage(operations,resources)){
    return {kind:"invalid",code:"ELEVATION_SCOPE_INVALID"}
  }
  if(typeof crypto==="undefined"||typeof crypto.randomUUID!=="function"){
    return {kind:"unavailable",code:"SECURE_CONTEXT_REQUIRED"}
  }
  const operation=crypto.randomUUID(),keys=resources.map(scopeKey).sort()
  try{
    const response=await fetch(CONTROL_PANEL_API_V1+"/approvals",{
      method:"POST",signal,credentials:"same-origin",mode:"same-origin",redirect:"error",
      cache:"no-store",referrerPolicy:"no-referrer",
      headers:{Accept:"application/json","Content-Type":"application/json",
        "Operation-UUID":operation,"Idempotency-Key":operation},
      body:JSON.stringify({project_uuid:project,agent_session_uuid:session,
        operations,resources,seconds,expected_grant_revision:revision}),
    })
    if(signal.aborted)return {kind:"uncertain",code:"ELEVATION_OUTCOME_UNCERTAIN"}
    if(response.status!==202){
      // 5xx can follow a committed owner write: do not promise a safe retry.
      const kind=response.status===401?"unauthorized":response.status===403?"forbidden":
        response.status===409?"conflict":response.status===422?"invalid":"uncertain"
      return {kind,code:"ELEVATION_HTTP_"+response.status}
    }
    const row=parseApproval(await response.json(),project)
    if(signal.aborted)return {kind:"uncertain",code:"ELEVATION_OUTCOME_UNCERTAIN"}
    if(!row||row.id!==operation||row.agent_session_uuid!==session||row.requested_by_user_uuid!==actorUuid||
      row.status!=="pending"||row.version!==1||row.allowed_actions.length!==0||
      row.resolved_by_user_uuid!==null||row.issued_session_uuid!==null||
      !(Date.parse(row.requested_expires_at)>Date.now())||
      Date.parse(row.requested_expires_at)>Date.now()+seconds*1000+1000||
      row.requested_operations.length!==operations.length||
      row.requested_operations.some(action=>!operations.includes(action))||
      JSON.stringify(row.requested_resources.map(scopeKey).sort())!==JSON.stringify(keys)){
      return {kind:"uncertain",code:"ELEVATION_PENDING_NOT_VERIFIED"}
    }
    return {kind:"pending",item:row}
  }catch{return {kind:"uncertain",code:"ELEVATION_OUTCOME_UNCERTAIN"}}
}
