import type { AccessProjection, PlatformPort } from "@/features/platform/model/contracts"
import { acceptedA6Source } from "@/features/platform/api/draft/source-acceptance"

/**
 * The cutover is intentionally NOT a runtime feature flag. It requires an
 * independently approved, actually mounted trusted server composition and
 * a verified current principal. The only accepted A4 API is unmounted SOURCE.
 *
 * This is the future integration contract for the orchestrator/reviewer, not
 * a credential or permission check and not an authority users can supply.
 */
export type PlatformCutoverPrerequisite =
  | "approved-public-api-contract"
  | "server-verified-active-principal"
  | "same-origin-https-trust-boundary"
  | "server-owned-permission-revisions"
  | "revocable-token-lifecycle"
  | "safe-command-status-reconciliation"
  | "authenticated-scoped-ws-revocation"
  | "independent-browser-runtime-acceptance"

export interface ReviewedPlatformRuntimeComposition {
  /** Future implementation must come from approved app composition, not UI. */
  readonly client: PlatformPort
  readonly publicContractVersion: string
  /** Verified by a REAL authenticated server call; never a stored username. */
  verifyCurrentPrincipal(signal:AbortSignal):Promise<AccessProjection | null>
  /** The reviewed app owns cleanup on login/logout/service revocation. */
  destroy():void
}

export const platformCutoverReadiness: Readonly<{
  state:"blocked"
  acceptedSource:typeof acceptedA6Source.source
  missing:readonly PlatformCutoverPrerequisite[]
}> = Object.freeze({
  state:"blocked",
  acceptedSource:acceptedA6Source.source,
  missing:Object.freeze([
    "approved-public-api-contract",
    "server-verified-active-principal",
    "same-origin-https-trust-boundary",
    "server-owned-permission-revisions",
    "revocable-token-lifecycle",
    "safe-command-status-reconciliation",
    "authenticated-scoped-ws-revocation",
    "independent-browser-runtime-acceptance",
  ] as const),
})

/**
 * Future cutover must implement an independently reviewed installer that
 * consumes ReviewedPlatformRuntimeComposition after all public gates close.
 * There is intentionally no callable activate/enable path in B8.
 */
export function cutoverBlocked():never {
  throw new Error("C1-B2-PUBLIC/C2 platform transport and verified runtime are not approved")
}
