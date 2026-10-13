/** Same-origin BFF-only Rauthy sign-in; never stores OAuth tokens or secrets. */
export type RauthyPanelIdentity = {
  authenticated: true
  authority: "rauthy"
  subject: string
  issuer: string
  client_id: string
  expires_at: string
  platform_membership_verified: false
  permissions: []
}

export type RauthyPanelState =
  | { kind: "unavailable" }
  | { kind: "signed_out" }
  | { kind: "signed_in"; identity: RauthyPanelIdentity }

const CONFIG = "/api/auth/oidc/config"
const SESSION = "/api/auth/oidc/session"
const LOGOUT = "/api/auth/oidc/logout"

function isVerifiedIdentity(value: unknown): value is RauthyPanelIdentity {
  if (typeof value !== "object" || value === null) return false
  const item = value as Record<string, unknown>
  return item.authenticated === true
    && item.authority === "rauthy"
    && typeof item.subject === "string"
    && item.subject.length > 0
    && typeof item.issuer === "string"
    && item.issuer.startsWith("https://")
    && typeof item.client_id === "string"
    && item.client_id.length > 0
    && typeof item.expires_at === "string"
    && item.platform_membership_verified === false
    && Array.isArray(item.permissions)
    && item.permissions.length === 0
}

/** Config 200 is not enough: session 401 demonstrates mounted OIDC BFF routes. */
export async function readRauthyPanelState(signal: AbortSignal): Promise<RauthyPanelState> {
  const request = {
    method: "GET",
    signal,
    credentials: "same-origin" as const,
    mode: "same-origin" as const,
    redirect: "error" as const,
    referrerPolicy: "no-referrer" as const,
    cache: "no-store" as const,
    headers: { Accept: "application/json" },
  }
  try {
    const config = await fetch(CONFIG, request)
    if (!config.ok) return { kind: "unavailable" }
    const metadata: unknown = await config.json()
    if (typeof metadata !== "object" || metadata === null) return { kind: "unavailable" }
    const fields = metadata as Record<string, unknown>
    if (typeof fields.issuer !== "string" || typeof fields.client_id !== "string"
      || fields.issuer.length < 12 || fields.client_id.length === 0) {
      return { kind: "unavailable" }
    }
    const response = await fetch(SESSION, request)
    if (response.status === 401) return { kind: "signed_out" }
    if (!response.ok) return { kind: "unavailable" }
    const identity: unknown = await response.json()
    return isVerifiedIdentity(identity)
      ? { kind: "signed_in", identity }
      : { kind: "unavailable" }
  } catch {
    return { kind: "unavailable" }
  }
}

/** Confirmation requires 204 from private Valkey session revocation. */
export async function signOutRauthyPanel(signal: AbortSignal): Promise<boolean> {
  try {
    const response = await fetch(LOGOUT, {
      method: "POST",
      signal,
      credentials: "same-origin",
      mode: "same-origin",
      redirect: "error",
      referrerPolicy: "no-referrer",
      cache: "no-store",
    })
    return response.status === 204
  } catch {
    return false
  }
}
