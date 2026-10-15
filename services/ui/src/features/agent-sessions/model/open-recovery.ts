import {prepareNormalSessionOpen,type PreparedNormalSessionOpen,type ElevationPolicy} from "../api/open-normal"

export interface PendingSessionOpen {
  readonly ownerKey:string
  readonly command:PreparedNormalSessionOpen
}
export type SessionOpenReservation=
  | {kind:"reserved";entry:PendingSessionOpen}
  | {kind:"invalid"|"unavailable"|"conflict";code:string}

/** A route-independent memory journal owned by one Control Panel instance.
 * Contains request intents, not tokens or grants. Nothing goes to browser
 * storage. An unresolved intent cannot be silently replaced by a new one.
 */
export function createSessionOpenRecovery(){
  const pending=new Map<string,PendingSessionOpen>()
  const key=(owner:string,project:string)=>JSON.stringify([owner,project])
  return {
    get(owner:string,project:string):PendingSessionOpen|null {
      return pending.get(key(owner,project))??null
    },
    reserve(owner:string,project:string,policy:ElevationPolicy,label:string):SessionOpenReservation {
      if(!owner||owner.length>4096)return {kind:"invalid",code:"SESSION_OWNER_SCOPE_INVALID"}
      if(pending.has(key(owner,project)))return {kind:"conflict",code:"SESSION_OPEN_ALREADY_PENDING"}
      if(pending.size>=100)return {kind:"unavailable",code:"SESSION_OPEN_RECOVERY_FULL"}
      const prepared=prepareNormalSessionOpen(project,policy,label)
      if(prepared.kind!=="prepared")return prepared
      const entry=Object.freeze({ownerKey:owner,command:prepared.command})
      pending.set(key(owner,project),entry)
      return {kind:"reserved",entry}
    },
    isCurrent(entry:PendingSessionOpen):boolean {
      return pending.get(key(entry.ownerKey,entry.command.project))===entry
    },
    complete(entry:PendingSessionOpen):void {
      const id=key(entry.ownerKey,entry.command.project)
      if(pending.get(id)===entry)pending.delete(id)
    },
    retainOwner(owner:string):void {
      for(const [id,entry] of pending)if(entry.ownerKey!==owner)pending.delete(id)
    },
    clear():void {pending.clear()},
  }
}
export type SessionOpenRecovery=ReturnType<typeof createSessionOpenRecovery>
export function sessionOpenOwnerKey(issuer:string,subject:string,clientId:string,actorId:string):string {
  return JSON.stringify([issuer,subject,clientId,actorId])
}
