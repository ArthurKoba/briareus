/** Local HTTP is suitable for UI/layout and owner-authorized noncredentialed
 * API testing. It is NOT proof that this host has a provider-safe OAuth
 * callback or browser cookie contract.
 */
export function needsApprovedHttpCallback(location:Pick<Location,"protocol"|"hostname">):boolean {
  return location.protocol==="http:" && (location.hostname==="127.0.0.1"||location.hostname==="localhost")
}
