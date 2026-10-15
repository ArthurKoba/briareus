import {executeNormalSessionOpen,normalSessionReplayRemaining,type ElevationPolicy,type NormalSessionResult} from "../api/open-normal"
import type {PendingSessionOpen,SessionOpenRecovery} from "./open-recovery"
export interface NormalOpenContext {
  ownerKey:string;actorId:string;projectId:string;proofExpiresAt:string;canOpen:boolean
}
type Verification="authorized"|"unauthorized"|"forbidden"|"unavailable"
export type VerifiedNormalOpen=NormalSessionResult|{kind:"cancelled";code:string}
/** Fresh owner check -> reserve one immutable intent -> one POST. The same
 * journal survives widget unmounts. A denial during retry cannot settle an
 * earlier ambiguous creation, and a different actor cannot consume it.
 */
export async function openVerifiedNormalSession(options:{
  policy:ElevationPolicy;label:string;saved:PendingSessionOpen|null
  journal:SessionOpenRecovery;signal:AbortSignal
  context:()=>NormalOpenContext|null;verify:(signal:AbortSignal)=>Promise<Verification>
}):Promise<VerifiedNormalOpen>{
  const first=options.context(),initial=first?{...first}:null,saved=options.saved
  let dispatched=false
  const current=():boolean=>{
    const value=options.context()
    return !!initial&&!!value&&!options.signal.aborted&&value.ownerKey===initial.ownerKey&&
      value.actorId===initial.actorId&&value.projectId===initial.projectId&&value.canOpen&&
      Date.parse(value.proofExpiresAt)>Date.now()
  }
  const invalidated=():VerifiedNormalOpen=>({kind:dispatched?"uncertain":"cancelled",code:"SESSION_OPEN_CONTEXT_CHANGED"})
  if(!current()||!initial)return invalidated()
  if(saved&&(!options.journal.isCurrent(saved)||saved.ownerKey!==initial.ownerKey||saved.command.project!==initial.projectId))return invalidated()
  if(saved&&normalSessionReplayRemaining(saved.command)<=0)return {kind:"unavailable",code:"SESSION_RECOVERY_WINDOW_ELAPSED"}
  try{
    const proof=await options.verify(options.signal)
    if(!current())return invalidated()
    if(proof!=="authorized")return {kind:proof,code:"SESSION_OWNER_NOT_VERIFIED"}
    let entry=saved
    if(!entry){
      const reserved=options.journal.reserve(initial.ownerKey,initial.projectId,options.policy,options.label)
      if(reserved.kind!=="reserved")return reserved
      entry=reserved.entry
    }
    if(!current()||!options.journal.isCurrent(entry))return invalidated()
    dispatched=true
    const result=await executeNormalSessionOpen(entry.command,options.signal)
    if(!current()||!options.journal.isCurrent(entry))return invalidated()
    if(result.kind==="created"||(!saved&&["unauthorized","forbidden","invalid"].includes(result.kind))){
      options.journal.complete(entry)
    }
    return result
  }catch{return {kind:dispatched?"uncertain":options.signal.aborted?"cancelled":"unavailable",code:"SESSION_OPEN_FLOW_UNAVAILABLE"}}
}
