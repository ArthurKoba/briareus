import type {CurrentAgentSession} from "../api/current-sessions"

/** A displayed scope from the latest accepted management snapshot, NOT a
 * Files execution grant. The actual Hand independently verifies Rauthy,
 * AgentSession and Cedar on every operation, including revoke and expiry.
 */
export interface FilesReadScopeSummary {
  sessionId:string
  revision:number
  expiresAt:string
  selector:string
}
export function filesReadScopes(
  records:readonly CurrentAgentSession[],project:string,now=Date.now(),
):FilesReadScopeSummary[]{
  const found:FilesReadScopeSummary[]=[],seen=new Set<string>()
  for(const record of records){
    if(record.project_uuid!==project||record.status!=="active"||
      Date.parse(record.hard_expires_at)<=now||!record.operations.includes("files.read"))continue
    for(const scope of record.resources){
      if(scope.hand!=="files"||scope.tool!=="read_file"||
        scope.action!=="files.read"||scope.resource.kind!=="workspace_path")continue
      const key=JSON.stringify([record.session_uuid,scope.resource.id])
      if(seen.has(key))continue
      seen.add(key)
      found.push({sessionId:record.session_uuid,revision:record.revision,
        expiresAt:record.hard_expires_at,selector:scope.resource.id})
    }
  }
  return found
}

/** Expiry of one session does not invalidate unexpired scopes from other
 * sessions. It is local presentation only; any actual Hand read still
 * requires a fresh owner/Cedar decision at the moment of execution. */
export function retainUnexpiredFilesReadScopes(
  records:readonly FilesReadScopeSummary[],now=Date.now(),
):FilesReadScopeSummary[]{
  return records.filter(record=>Number.isFinite(Date.parse(record.expiresAt))&&
    Date.parse(record.expiresAt)>now)
}
