import { readonly, shallowRef } from "vue"
import type { PlatformPort } from "@/features/platform/model/contracts"
import { cutoverBlocked } from "@/features/platform/api/cutover-contract"

/** There is deliberately NO default adapter, mock principal, endpoint or fallback. */
const current = shallowRef<PlatformPort | null>(null)

/**
 * Source-only B8: even a call from accidental or unreviewed composition code
 * cannot activate an unauthenticated draft transport. Future C1-B2/C2 approval
 * MUST replace this guard with an independently reviewed server-verifying
 * installer; a UI-provided `true` flag or locally minted token is insufficient.
 */
export function installPlatformPort(port: PlatformPort | null): void {
  if(port!==null)cutoverBlocked()
  current.value=null
}
export const platformPort = readonly(current)
