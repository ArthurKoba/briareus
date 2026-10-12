/** Strictly public, read-only OIDC discovery through the Control Panel API.
 * This is NOT an OAuth client and deliberately cannot start an authorization
 * request, generate PKCE state, exchange an auth code or store credentials.
 * The trusted Backend BFF must publish an accepted session/start contract.
 */
const CONFIG_ROUTE = "/api/auth/oidc/config"
const MAX_BYTES = 16384

export type OidcReadiness = "configured" | "unavailable" | "invalid"

function validHttpsUri(raw: unknown): boolean {
  if (typeof raw !== "string" || raw.length > 2048) return false
  try {
    const url = new URL(raw)
    return url.protocol === "https:" && Boolean(url.hostname) &&
      url.username === "" && url.password === "" &&
      url.search === "" && url.hash === ""
  } catch { return false }
}

async function boundedJson(response: Response): Promise<unknown> {
  const declared = response.headers.get("content-length")
  if (declared !== null && (!/^\d+$/.test(declared) || Number(declared) > MAX_BYTES)) {
    throw new Error("invalid oidc configuration size")
  }
  if (!response.body) throw new Error("missing oidc configuration")
  const reader = response.body.getReader()
  const fragments: Uint8Array[] = []
  let bytes = 0
  try {
    for (;;) {
      const { done, value } = await reader.read()
      if (done) break
      bytes += value.byteLength
      if (bytes > MAX_BYTES) throw new Error("invalid oidc configuration size")
      fragments.push(value)
    }
  } finally { reader.releaseLock() }
  const complete = new Uint8Array(bytes)
  let offset = 0
  for (const fragment of fragments) {
    complete.set(fragment, offset)
    offset += fragment.byteLength
  }
  return JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(complete)) as unknown
}

/** Distinguish a published trusted issuer configuration from an unconfigured BFF.
 * Even `configured` is NOT a grant to redirect: the BFF must broker PKCE,
 * callback validation, User session and sign-out independently.
 */
export async function checkOidcReadiness(signal: AbortSignal): Promise<OidcReadiness> {
  let response: Response
  try {
    response = await fetch(CONFIG_ROUTE, {
      method: "GET", signal, mode: "same-origin", credentials: "omit",
      cache: "no-store", redirect: "error", referrerPolicy: "no-referrer",
      headers: { Accept: "application/json" },
    })
  } catch { return "unavailable" }
  if (!response.ok) return "unavailable"
  try {
    const data = await boundedJson(response)
    if (!data || typeof data !== "object" || Array.isArray(data)) return "invalid"
    const metadata = data as Record<string, unknown>
    const keys = ["issuer", "client_id", "authorization_endpoint", "token_endpoint", "jwks_uri"]
    if (!keys.every(key => key in metadata) ||
      Object.keys(metadata).some(key => ![...keys, "userinfo_endpoint"].includes(key)) ||
      typeof metadata.client_id !== "string" || !metadata.client_id.trim() ||
      metadata.client_id.length > 256 ||
      ![metadata.issuer, metadata.authorization_endpoint, metadata.token_endpoint,
        metadata.jwks_uri].every(validHttpsUri) ||
      (metadata.userinfo_endpoint !== null && metadata.userinfo_endpoint !== undefined &&
        !validHttpsUri(metadata.userinfo_endpoint))) return "invalid"
    return "configured"
  } catch { return "invalid" }
}
