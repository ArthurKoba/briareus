import type { AccessProjection, PlatformPort } from "@/features/platform/model/contracts"
import { DraftContractError } from "@/features/platform/api/draft/source-contract"
import { acceptedA8Source } from "@/features/platform/api/draft/source-acceptance"
import { createUninstalledDraftConsumer, type DraftConsumer } from "@/features/platform/api/draft/source-port"

/**
 * A private, intentionally UNINSTALLED A8 source composition. Constructing
 * this object cannot install PlatformPort or make network calls. Its origin
 * must be explicitly supplied and passes the same-origin HTTPS/path guard.
 *
 * Only a future independently reviewed C1-B2/C2 composition root can replace
 * the permanently blocked public installer in api/port.ts.
 */
export interface DisabledFuturePlatformClient {
  readonly acceptance: typeof acceptedA8Source
  readonly port: PlatformPort
  /** A8 server-proven principal only; returns null when no memory token. */
  verifyCurrentPrincipal(signal: AbortSignal): Promise<AccessProjection | null>
  destroy(): void
}

export function createUninstalledFuturePlatformClient(explicitSameOriginUrl: string): DisabledFuturePlatformClient {
  if(acceptedA8Source.publicTransportAuthorized || acceptedA8Source.platformPortInstallAuthorized) {
    throw new DraftContractError("source_only_cutover_required")
  }
  const client:DraftConsumer=createUninstalledDraftConsumer(explicitSameOriginUrl)
  let destroyed=false
  return Object.freeze({
    acceptance:acceptedA8Source,
    port:client.port,
    async verifyCurrentPrincipal(signal:AbortSignal):Promise<AccessProjection|null> {
      if(destroyed||signal.aborted)throw new DraftContractError("future_client_unavailable")
      const projection=await client.port.auth.refresh(signal)
      if(destroyed||signal.aborted)throw new DraftContractError("future_client_invalidated")
      if(!projection)return null
      if(!projection.user.active)return null
      if(!projection.user.userId||!Array.isArray(projection.projects)||!Array.isArray(projection.teams)) {
        throw new DraftContractError("server_principal_projection_unverified")
      }
      return projection
    },
    destroy():void {
      if(destroyed)return
      destroyed=true
      client.destroy()
    },
  })
}
