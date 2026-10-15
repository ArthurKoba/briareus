import type {ApprovalRecord} from "../types"

/** A bounded owner-list snapshot may contain pending requests whose action
 * deadline elapsed after the GET. Hide only actionable elapsed requests;
 * preserve other pending approvals and the immutable resolved history.
 *
 * This is presentation ageing, NOT a local approve/deny, revoked grant,
 * mutation of the owner receipt, or evidence that a private Core request
 * was executed. New actions still require exact current owner/Cedar proof.
 */
export function pruneElapsedApprovalRows(
  rows:readonly ApprovalRecord[],
  cutoff:number,
):{items:ApprovalRecord[];removed:number}{
  if(!Number.isFinite(cutoff))return {items:[],removed:rows.length}
  const items=rows.filter(row=>
    row.status!=="pending"||row.allowed_actions.length===0||
      (Number.isFinite(Date.parse(row.requested_expires_at))&&
        Date.parse(row.requested_expires_at)>cutoff)
  )
  return {items,removed:rows.length-items.length}
}
