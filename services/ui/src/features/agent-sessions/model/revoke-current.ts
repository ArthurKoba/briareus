import {readCurrentSession,revokeCurrentSession,type CurrentAgentSession} from "../api/current-sessions"

export interface SessionCommandContext {
  projectId:string
  actorId:string
  proofExpiresAt:string
  canApprove:boolean
}
type Verification="authorized"|"unauthorized"|"forbidden"|"unavailable"
export type ReconciledRevoke=
  | {kind:"confirmed"|"conflict"|"observed";item:CurrentAgentSession}
  | {kind:"cancelled"|"unauthorized"|"forbidden"|"invalid"|"unavailable"|"uncertain";code:string}

/** Fresh Project membership -> exact current row -> one revision-fenced POST
 * -> exact current row. List truncation cannot masquerade as a revoke result.
 * UI context is a cancellation guard, never a server authorization grant.
 */
export async function revokeVerifiedSession(
  selected:CurrentAgentSession,
  options:{signal:AbortSignal;context:()=>SessionCommandContext|null;verify:(signal:AbortSignal)=>Promise<Verification>},
):Promise<ReconciledRevoke>{
  const initial=options.context()
  const project=initial?.projectId,actor=initial?.actorId
  const id=selected.session_uuid,revision=selected.revision,creator=selected.created_by_user_uuid
  let dispatched=false
  const current=():boolean=>{
    const context=options.context()
    return !options.signal.aborted&&!!initial&&!!context&&context.projectId===project&&
      context.actorId===actor&&context.canApprove&&Date.parse(context.proofExpiresAt)>Date.now()
  }
  const invalidated=():ReconciledRevoke=>({kind:dispatched?"uncertain":"cancelled",code:"REVOKE_CONTEXT_CHANGED"})
  if(!initial||selected.project_uuid!==project||selected.status!=="active"||
    !selected.allowed_actions.includes("revoke")||Date.parse(selected.hard_expires_at)<=Date.now()){
    return {kind:"forbidden",code:"REVOKE_NOT_ALLOWED"}
  }
  if(!current())return invalidated()
  try{
    const verdict=await options.verify(options.signal)
    if(!current())return invalidated()
    if(verdict!=="authorized")return {kind:verdict,code:"REVOKE_OWNER_NOT_VERIFIED"}
    const before=await readCurrentSession(initial.projectId,id,initial.actorId,true,options.signal)
    if(!current())return invalidated()
    if(before.kind!=="ready")return {kind:before.kind==="conflict"||before.kind==="not_found"?"unavailable":before.kind,code:before.code}
    const fresh=before.item
    if(fresh.revision!==revision||fresh.created_by_user_uuid!==creator||
      fresh.status!=="active"||!fresh.allowed_actions.includes("revoke")){
      return {kind:"conflict",item:fresh}
    }
    dispatched=true
    const receipt=await revokeCurrentSession(fresh,options.signal)
    if(!current())return invalidated()
    if(receipt.kind!=="confirmed"&&receipt.kind!=="conflict"&&receipt.kind!=="uncertain"&&receipt.kind!=="unavailable"){
      return {kind:receipt.kind,code:receipt.code}
    }
    if(receipt.kind==="unavailable"&&["SECURE_CONTEXT_REQUIRED","REVOKE_CANCELLED_BEFORE_DISPATCH"].includes(receipt.code)){
      return {kind:"unavailable",code:receipt.code}
    }
    const after=await readCurrentSession(initial.projectId,id,initial.actorId,true,options.signal)
    if(!current())return invalidated()
    if(after.kind!=="ready")return {kind:"uncertain",code:"REVOKE_NOT_RECONCILED"}
    if(after.item.created_by_user_uuid!==creator||after.item.revision<revision){
      return {kind:"uncertain",code:"REVOKE_RESULT_CONTRADICTED"}
    }
    if(receipt.kind==="conflict")return {kind:"conflict",item:after.item}
    // Lost POST replies allow only a current-state observation. Do not
    // attribute the change to this request or invent a missing receipt.
    if(receipt.kind!=="confirmed")return {kind:"observed",item:after.item}
    if(after.item.status!=="revoked"||after.item.revision<receipt.revision||
      after.item.created_by_user_uuid!==creator||after.item.allowed_actions.length!==0){
      return {kind:"uncertain",code:"REVOKE_RESULT_CONTRADICTED"}
    }
    return {kind:"confirmed",item:after.item}
  }catch{return {kind:dispatched?"uncertain":options.signal.aborted?"cancelled":"unavailable",code:"REVOKE_FLOW_UNAVAILABLE"}}
}
