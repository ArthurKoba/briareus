import type { RauthyPanelState } from "../api/rauthy-oidc"

/** A child echo of the parent snapshot is not a logout/login event.
 * Compare the actual identity binding, never just its signed_in label.
 */
export function providerStateChanged(previous:RauthyPanelState|null,next:RauthyPanelState):boolean {
  if(!previous||previous.kind!==next.kind)return true
  if(previous.kind==="signed_out"&&next.kind==="signed_out")return false
  if(previous.kind==="unavailable"&&next.kind==="unavailable")return previous.reason!==next.reason
  if(previous.kind==="signed_in"&&next.kind==="signed_in")return (
    previous.identity.issuer!==next.identity.issuer||
    previous.identity.subject!==next.identity.subject||
    previous.identity.client_id!==next.identity.client_id||
    previous.identity.expires_at!==next.identity.expires_at
  )
  return true
}
