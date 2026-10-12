/** Temporary, owner-requested bridge to EXISTING Identity-owned BFF routes.
 * Retire on verified Rauthy cutover; never synthesize Platform grants or a User role.
 * Bearer stays in module memory, never in cookies, storage, URL or logs.
 */
export interface VerifiedFirstUser {
  user_id: string
  credential_version: number
  source: "verified-admin-bearer"
}

export type FirstUserErrorCode =
  | "AUTHENTICATION_REQUIRED" | "INVITATION_REJECTED" | "AUTHENTICATION_RATE_LIMITED"
  | "REQUEST_REJECTED" | "OWNER_SOURCE_UNAVAILABLE" | "NETWORK_ERROR" | "BAD_RESPONSE"

export class FirstUserError extends Error {
  constructor(readonly code: FirstUserErrorCode) { super(code) }
}

let bearer: string | null = null
const UUID4 = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/

function errorForStatus(status: number): FirstUserError {
  if (status === 401) return new FirstUserError("AUTHENTICATION_REQUIRED")
  if (status === 403) return new FirstUserError("INVITATION_REJECTED")
  if (status === 429) return new FirstUserError("AUTHENTICATION_RATE_LIMITED")
  if (status === 422) return new FirstUserError("REQUEST_REJECTED")
  if (status === 503) return new FirstUserError("OWNER_SOURCE_UNAVAILABLE")
  return new FirstUserError("BAD_RESPONSE")
}

async function request(
  path: "/api/auth/login" | "/api/auth/register" | "/api/auth/logout" | "/api/platform/me",
  options: { method: "GET" | "POST"; body?: unknown; token?: string; signal?: AbortSignal },
): Promise<Response> {
  const op = options.method === "POST" ? crypto.randomUUID() : null
  const controller = new AbortController()
  const cancel = () => controller.abort()
  if(options.signal?.aborted) throw new FirstUserError("NETWORK_ERROR")
  options.signal?.addEventListener("abort", cancel, {once:true})
  const deadline = setTimeout(cancel, 12000)
  try {
    return await fetch(path, {
      method: options.method,
      signal: controller.signal,
      mode: "same-origin",
      credentials: "omit",
      cache: "no-store",
      redirect: "error",
      referrerPolicy: "no-referrer",
      headers: {
        Accept: "application/json",
        ...(options.body !== undefined ? { "Content-Type": "application/json" } : {}),
        ...(op ? { "Operation-UUID": op, "Idempotency-Key": op } : {}),
        ...(options.token ? { Authorization: `Bearer ${options.token}` } : {}),
      },
      ...(options.body !== undefined ? { body: JSON.stringify(options.body) } : {}),
    })
  } catch {
    throw new FirstUserError("NETWORK_ERROR")
  } finally {
    clearTimeout(deadline)
    options.signal?.removeEventListener("abort", cancel)
  }
}
function asObject(input: unknown): Record<string, unknown> | null {
  return typeof input === "object" && input !== null && !Array.isArray(input)
    ? input as Record<string, unknown> : null
}
async function bodyObject(response: Response): Promise<Record<string, unknown>> {
  try {
    const parsed = asObject(await response.json())
    if (parsed) return parsed
  } catch { /* no response body is accepted as an identity */ }
  throw new FirstUserError("BAD_RESPONSE")
}
function verified(input: unknown): VerifiedFirstUser {
  const data = asObject(input)
  if (!data || typeof data.user_id !== "string" || !UUID4.test(data.user_id) ||
      (typeof data.credential_version !== "number" || !Number.isInteger(data.credential_version)) || (data.credential_version as number) < 1 ||
      data.source !== "verified-admin-bearer") throw new FirstUserError("BAD_RESPONSE")
  return {
    user_id: data.user_id,
    credential_version: data.credential_version as number,
    source: "verified-admin-bearer",
  }
}
export async function signInFirstUser(username: string, password: string, signal?: AbortSignal): Promise<VerifiedFirstUser> {
  // Do not retain a prior principal when credentials are submitted.
  bearer = null
  const response = await request("/api/auth/login", { method: "POST", body: { username, password }, signal })
  if (response.status !== 200) throw errorForStatus(response.status)
  const receipt = await bodyObject(response)
  if (receipt.token_type !== "Bearer" || typeof receipt.access_token !== "string" ||
      receipt.access_token.length < 40 || receipt.access_token.length > 8192 ||
      typeof receipt.expires_at !== "string" ||
      !Number.isFinite(Date.parse(receipt.expires_at)) ||
      Date.parse(receipt.expires_at) <= Date.now()) throw new FirstUserError("BAD_RESPONSE")
  const token = receipt.access_token
  const current = await request("/api/platform/me", { method: "GET", token, signal })
  if (current.status !== 200) throw errorForStatus(current.status)
  const identity = verified(await bodyObject(current))
  if(signal?.aborted) throw new FirstUserError("NETWORK_ERROR")
  bearer = token
  return identity
}
export async function registerFirstUser(invitation: string, username: string, password: string, signal?: AbortSignal): Promise<void> {
  const response = await request("/api/auth/register", {
    method: "POST", body: { invitation, username, password }, signal,
  })
  if (response.status !== 201) throw errorForStatus(response.status)
  const receipt = await bodyObject(response)
  if (typeof receipt.user_id !== "string" || !UUID4.test(receipt.user_id) ||
      !["user", "superuser"].includes(String(receipt.role))) throw new FirstUserError("BAD_RESPONSE")
}
export async function signOutFirstUser(): Promise<boolean> {
  const token = bearer
  bearer = null
  if (!token) return true
  try {
    const result = await request("/api/auth/logout", { method: "POST", token })
    return result.status === 204
  } catch { return false }
}
export function clearTemporaryBearer(): void { bearer = null }
