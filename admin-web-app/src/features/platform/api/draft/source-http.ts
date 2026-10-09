import { DraftContractError, parseDraftToken, type DraftAdminToken } from "@/features/platform/api/draft/source-contract"
import { requireSourceRoute, type SourceMethod } from "@/features/platform/api/draft/source-routes"

/**
 * Private SOURCE-ONLY transport for unmounted draft Pydantic routes.
 * Not imported/installed by App; never assume the old Admin username cookie is a principal.
 * Protected requests require an in-memory verified bearer token, never localStorage.
 */
export class DraftHttpError extends Error {
  readonly status: number | null
  readonly code: string
  readonly kind: "http" | "network" | "aborted"
  constructor(status: number | null, code: string, kind: "http" | "network" | "aborted" = "http") {
    super("Draft Admin source transport request failed")
    this.name = "DraftHttpError"
    this.status = status
    this.code = code
    this.kind = kind
  }
}
export interface DraftHttpRequest {
  signal?: AbortSignal
  idempotencyKey?: string
  ifMatchVersion?: number
  public?: boolean
}

function validateBaseUrl(baseUrl: string): string {
  const url = new URL(baseUrl)
  if (url.username || url.password || url.search || url.hash || url.pathname.replace(/\/+$/, "") !== "/v1/platform") {
    throw new DraftContractError("draft_api_base_invalid")
  }
  const localhost = ["localhost", "127.0.0.1", "[::1]"].includes(url.hostname)
  if (url.protocol !== "https:" && !(url.protocol === "http:" && localhost)) throw new DraftContractError("https_required")
  // C1-B2/C2 must approve any cross-origin bearer/CORS/proxy arrangement.
  if (typeof location !== "undefined" && url.origin !== location.origin) throw new DraftContractError("cross_origin_not_approved")
  return url.toString().replace(/\/+$/, "")
}
function assertVersion(version: number): string {
  if (!Number.isSafeInteger(version) || version < 1) throw new DraftContractError("revision_required")
  return String(version)
}
function assertKey(key: string): string {
  if (key.length < 1 || key.length > 128 || !/^[\x21-\x7e]+$/.test(key)) throw new DraftContractError("idempotency_key_invalid")
  return key
}

/** Bounded JSON decoder: no untrusted error-body reflection or unbounded list buffering. */
const MAX_SOURCE_BODY_BYTES = 4 * 1024 * 1024
async function readSourceJson(response: Response): Promise<unknown> {
  const mediaType=(response.headers.get("content-type")??"").toLowerCase().split(";")[0]?.trim()??""
  if (mediaType!=="application/json" && !mediaType.endsWith("+json")) {
    throw new DraftContractError("source_json_content_type_required")
  }
  const sizeHeader=response.headers.get("content-length")
  if (sizeHeader!==null && /^\d+$/.test(sizeHeader) && Number(sizeHeader)>MAX_SOURCE_BODY_BYTES) {
    throw new DraftContractError("source_json_response_too_large")
  }
  if (!response.body) {
    const value=await response.text()
    if (new TextEncoder().encode(value).byteLength>MAX_SOURCE_BODY_BYTES) {
      throw new DraftContractError("source_json_response_too_large")
    }
    return JSON.parse(value) as unknown
  }
  const reader=response.body.getReader()
  const decoder=new TextDecoder("utf-8",{fatal:true})
  let raw="",size=0
  try {
    while(true){
      const chunk=await reader.read()
      if(chunk.done)break
      size+=chunk.value.byteLength
      if(size>MAX_SOURCE_BODY_BYTES){
        await reader.cancel()
        throw new DraftContractError("source_json_response_too_large")
      }
      raw+=decoder.decode(chunk.value,{stream:true})
    }
    raw+=decoder.decode()
  } finally {reader.releaseLock()}
  return JSON.parse(raw) as unknown
}

export type DraftCredentialChange = "established" | "invalidated" | "expired"
export class DraftSourceHttp {
  private readonly base: string
  private token: string | null = null
  private expiresAt = 0
  private epoch = 0
  private expiryTimer: ReturnType<typeof setTimeout> | null = null
  private readonly requests = new Set<AbortController>()
  private readonly listeners = new Set<(change: DraftCredentialChange) => void>()
  constructor(baseUrl: string) { this.base = validateBaseUrl(baseUrl) }

  get hasVerifiedToken(): boolean {
    if (this.token && Date.now() >= this.expiresAt) this.clearCredential("expired")
    return Boolean(this.token && Date.now() < this.expiresAt)
  }
  onCredentialChange(listener: (change: DraftCredentialChange) => void): () => void {
    this.listeners.add(listener)
    return () => { this.listeners.delete(listener) }
  }
  private announce(change: DraftCredentialChange): void {
    // No token, claims, request body or User ID may leave this transport event.
    for (const listener of this.listeners) listener(change)
  }
  private scheduleExpiry(): void {
    if (!this.token || this.expiryTimer) return
    const remaining = this.expiresAt - Date.now()
    if (remaining <= 0) { this.clearCredential("expired"); return }
    this.expiryTimer = setTimeout(() => {
      this.expiryTimer = null
      if (this.token) this.scheduleExpiry()
    }, Math.min(remaining, 2_147_483_647))
  }
  clearCredential(reason: "invalidated" | "expired" = "invalidated"): void {
    const hadCredential = this.token !== null
    ++this.epoch
    if (this.expiryTimer !== null) { clearTimeout(this.expiryTimer); this.expiryTimer = null }
    this.token = null
    this.expiresAt = 0
    for (const request of this.requests) request.abort()
    this.requests.clear()
    if (hadCredential) this.announce(reason)
  }
  adoptIssuedToken(raw: unknown): void {
    const token: DraftAdminToken = parseDraftToken(raw)
    // A refresh swaps credentials in one coherent step. Emitting a transient
    // "invalidated" event here would incorrectly log out a valid refresh.
    ++this.epoch
    if (this.expiryTimer!==null) {clearTimeout(this.expiryTimer);this.expiryTimer=null}
    for (const request of this.requests) request.abort()
    this.requests.clear()
    this.token=token.access_token
    this.expiresAt=Date.parse(token.expires_at)
    this.scheduleExpiry()
    this.announce("established")
  }
  destroy(): void {
    this.clearCredential()
    this.listeners.clear()
  }
  async request(
    method: SourceMethod,
    path: string,
    body?: unknown,
    options: DraftHttpRequest = {},
  ): Promise<unknown> {
    requireSourceRoute(method, path)
    if (options.public && !(method === "POST" && ["/auth/login", "/registration", "/password/reset"].includes(path))) {
      throw new DraftContractError("public_route_not_source_authorized")
    }
    if (method === "GET" && body !== undefined) throw new DraftContractError("get_request_body")
    if (method !== "GET" && !["/auth/logout", "/auth/refresh"].includes(path) && !options.public && !options.idempotencyKey) throw new DraftContractError("idempotency_key_required")
    if(method==="POST" && ["/registration","/password/reset"].includes(path) && !options.idempotencyKey){
      throw new DraftContractError("one_use_idempotency_key_required")
    }
    if (options.idempotencyKey) assertKey(options.idempotencyKey)
    if (options.ifMatchVersion !== undefined) assertVersion(options.ifMatchVersion)
    if (!options.public && !this.hasVerifiedToken) {
      this.clearCredential()
      throw new DraftHttpError(401, "authentication_required")
    }
    const requestGeneration = this.epoch
    const controller = new AbortController()
    this.requests.add(controller)
    const signal = options.signal ? AbortSignal.any([controller.signal, options.signal]) : controller.signal
    const headers = new Headers({ Accept: "application/json" })
    if (body !== undefined) headers.set("Content-Type", "application/json")
    if (!options.public && this.token) headers.set("Authorization", `Bearer ${this.token}`)
    if (options.idempotencyKey) headers.set("Idempotency-Key", options.idempotencyKey)
    if (options.ifMatchVersion !== undefined) headers.set("If-Match-Version", assertVersion(options.ifMatchVersion))
    try {
      const response = await fetch(this.base + path, {
        method, headers, body: body === undefined ? undefined : JSON.stringify(body), signal,
        credentials: "omit", cache: "no-store", redirect: "error", referrerPolicy: "no-referrer",
      })
      if (requestGeneration !== this.epoch || signal.aborted) throw new DraftHttpError(null, "context_changed", "aborted")
      if (!response.ok) {
        let code = "draft_http_error"
        // Parse only a structured versioned error code; NEVER surface raw message/body.
        try {
          const envelope: unknown = await readSourceJson(response)
          if (envelope && typeof envelope === "object" && "error" in envelope) {
            const detail = (envelope as Record<string, unknown>).error
            if (detail && typeof detail === "object" && !Array.isArray(detail)) {
              const fields = detail as Record<string, unknown>
              if (fields.version === 1 && fields.status === response.status && typeof fields.code === "string" &&
                  /^[a-z0-9_.-]{1,96}$/i.test(fields.code)) code = fields.code
            }
          }
        } catch { /* Error body intentionally discarded. */ }
        if (requestGeneration !== this.epoch || signal.aborted) throw new DraftHttpError(null, "context_changed", "aborted")
        if (response.status === 401 && !options.public) this.clearCredential()
        throw new DraftHttpError(response.status, code)
      }
      if (response.status === 204) return null
      const result: unknown = await readSourceJson(response)
      if (requestGeneration !== this.epoch || signal.aborted) throw new DraftHttpError(null, "context_changed", "aborted")
      return result
    } catch (cause) {
      if (cause instanceof DraftHttpError || cause instanceof DraftContractError) throw cause
      if (signal.aborted || (cause instanceof DOMException && cause.name === "AbortError")) throw new DraftHttpError(null, "request_cancelled", "aborted")
      throw new DraftHttpError(null, "outcome_unconfirmed", "network")
    } finally {
      this.requests.delete(controller)
    }
  }
}
