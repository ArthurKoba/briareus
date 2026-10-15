import type {CurrentAgentSession} from "../api/current-sessions"

/** Presentation-only ageing of one bounded owner snapshot. Do not transform
 * "active" into a server-"expired" state or infer Cedar revocation locally.
 * Once an active row passes its hard deadline, remove that particular row,
 * preserving unrelated unexpired sessions and historical owner records.
 */
export function pruneElapsedSessionRows(
  rows:readonly CurrentAgentSession[],elapsedBefore:number,
):{items:CurrentAgentSession[];removed:number}{
  if(!Number.isFinite(elapsedBefore))return {items:[],removed:rows.length}
  const items=rows.filter(row=>
    row.status!=="active"||
    (Number.isFinite(Date.parse(row.hard_expires_at))&&
      Date.parse(row.hard_expires_at)>elapsedBefore)
  )
  return {items,removed:rows.length-items.length}
}
