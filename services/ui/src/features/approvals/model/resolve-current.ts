import {
  approvalStillCurrentForActor, readProjectApprovals, resolveProjectApproval, sameRequestedEffect,
  type ApprovalRecord, type ApprovalAction,
} from "../api/control-panel"

export interface ApprovalCommandContext {
  projectId:string
  actorId:string
  proofExpiresAt:string
  canApprove:boolean
  rows:readonly ApprovalRecord[]
}
type Verification="authorized"|"unauthorized"|"forbidden"|"unavailable"
export type CurrentApprovalResult=
  | {kind:"confirmed"|"conflict"|"observed";items:ApprovalRecord[]}
  | {kind:"cancelled"|"unauthorized"|"forbidden"|"invalid"|"unavailable"|"uncertain"}

/** One explicit decision: fresh membership -> fresh revision -> one POST ->
 * fresh GET confirmation. Renewing the same owner proof is not revocation.
 * Changing actor/project/rights or aborting invalidates every later step.
 */
export async function resolveCurrentApproval(
  selected:ApprovalRecord,
  action:ApprovalAction,
  options:{
    signal:AbortSignal
    context:()=>ApprovalCommandContext|null
    verify:(signal:AbortSignal)=>Promise<Verification>
  },
):Promise<CurrentApprovalResult>{
  const initial=options.context()
  const projectId=initial?.projectId,actorId=initial?.actorId
  let writeIssued=false
  const current=():ApprovalCommandContext|null=>{
    const value=options.context()
    return !options.signal.aborted&&initial&&value&&value.projectId===projectId&&
      value.actorId===actorId&&value.canApprove&&
      Date.parse(value.proofExpiresAt)>Date.now()?value:null
  }
  const cancelled=():CurrentApprovalResult=>({kind:writeIssued?"uncertain":"cancelled"})
  if(!initial||!current()||!approvalStillCurrentForActor(
    selected,initial.rows,action,initial.projectId,initial.actorId,
  ))return {kind:"forbidden"}
  try{
    const verdict=await options.verify(options.signal)
    let context=current()
    if(!context)return cancelled()
    if(verdict!=="authorized")return {kind:verdict}
    if(!approvalStillCurrentForActor(selected,context.rows,action,context.projectId,context.actorId)){
      return {kind:"conflict",items:[...context.rows]}
    }
    const before=await readProjectApprovals(initial.projectId,options.signal)
    context=current()
    if(!context)return cancelled()
    if(before.kind!=="ready")return {kind:before.kind==="conflict"?"unavailable":before.kind}
    if(!approvalStillCurrentForActor(selected,before.items,action,initial.projectId,initial.actorId)){
      return {kind:"conflict",items:before.items}
    }
    // The fresh row is the write payload; no stale dialog-snapshot authority.
    const fresh=before.items.find(row=>row.id===selected.id)!
    writeIssued=true
    const decision=await resolveProjectApproval(fresh,action,options.signal)
    if(!current())return cancelled()
    if(decision.kind!=="confirmed"&&decision.kind!=="conflict"&&decision.kind!=="uncertain"&&decision.kind!=="unavailable"){
      return {kind:decision.kind}
    }
    if(decision.kind==="unavailable"&&["SECURE_CONTEXT_REQUIRED","APPROVAL_CANCELLED_BEFORE_DISPATCH"].includes(decision.code)){
      return {kind:"unavailable"}
    }
    if(decision.kind==="confirmed"&&decision.item.resolved_by_user_uuid!==initial.actorId){
      return {kind:"uncertain"}
    }
    const after=await readProjectApprovals(initial.projectId,options.signal)
    if(!current())return cancelled()
    if(after.kind!=="ready")return {kind:"uncertain"}
    const actual=after.items.find(row=>row.id===selected.id)
    // No attribution from list absence or a different requested effect.
    if(!actual||!sameRequestedEffect(actual,selected))return {kind:"uncertain"}
    if(decision.kind==="conflict")return {kind:"conflict",items:after.items}
    if(decision.kind!=="confirmed"){
      const expectedVersion=actual.status==="pending"?selected.version:selected.version+1
      return actual.version===expectedVersion?{kind:"observed",items:after.items}:{kind:"uncertain"}
    }
    if(actual.status!==decision.item.status||actual.version!==decision.item.version||
      actual.issued_session_uuid!==decision.item.issued_session_uuid||
      actual.resolved_by_user_uuid!==initial.actorId)return {kind:"uncertain"}
    return {kind:"confirmed",items:after.items}
  }catch{
    return {kind:writeIssued?"uncertain":options.signal.aborted?"cancelled":"unavailable"}
  }
}
