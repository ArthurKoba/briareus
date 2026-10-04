import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { ManagementApiError } from "@/shared/api/error"
import { managementApi } from "@/shared/api/management"

const notify = vi.hoisted(() => ({ error: vi.fn() }))
const telemetry = vi.hoisted(() => ({ api: vi.fn(), error: vi.fn() }))
vi.mock("@/shared/notifications/bus", () => ({ notifications: notify }))
vi.mock("@/shared/config/runtime", () => ({ runtimeConfig: { preview: false } }))
vi.mock("@/shared/telemetry/client", () => ({ frontendTelemetry: telemetry }))
vi.mock("@/shared/i18n", () => ({ i18n: { global: { t: (key: string) => key } } }))

beforeEach(() => {
  notify.error.mockReset()
  telemetry.api.mockReset()
  telemetry.error.mockReset()
})
afterEach(() => vi.unstubAllGlobals())

describe("management API error ownership", () => {
  it("reports a structured HTTP failure exactly once and preserves code/request ID", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(
      JSON.stringify({ error: { code: "upstream_failed", message: "Provider unavailable" } }),
      { status: 502, headers: { "content-type": "application/json", "x-request-id": "req-502" } },
    )))
    const error = await managementApi.accounts().catch(value => value)
    expect(error).toBeInstanceOf(ManagementApiError)
    expect(error).toMatchObject({ kind: "http", status: 502, code: "upstream_failed", requestId: "req-502" })
    expect(notify.error).toHaveBeenCalledTimes(1)
    expect(telemetry.api).toHaveBeenCalledTimes(1)
    expect(telemetry.error).not.toHaveBeenCalled()
  })

  it("parses FastAPI detail objects into a typed conflict error", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(
      JSON.stringify({ detail: { code: "settings_conflict", message: "settings changed", current_revision: "rev-2" } }),
      { status: 409, headers: { "content-type": "application/json" } },
    )))
    const error = await managementApi.settings().catch(value => value)
    expect(error).toBeInstanceOf(ManagementApiError)
    expect(error).toMatchObject({ kind: "http", status: 409, code: "settings_conflict" })
    expect(error.message).toBe("settings changed")
    expect(notify.error).toHaveBeenCalledTimes(1)
    expect(telemetry.error).not.toHaveBeenCalled()
  })

  it("keeps a non-JSON HTTP failure as one HTTP outcome", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("gateway exploded", { status: 500 })))
    const error = await managementApi.accounts().catch(value => value)
    expect(error).toMatchObject({ kind: "http", status: 500 })
    expect(error.message).toBe("Management API request failed: 500")
    expect(notify.error).toHaveBeenCalledTimes(1)
    expect(telemetry.error).not.toHaveBeenCalled()
  })

  it("does not expire auth on a 403 policy/origin failure", async () => {
    const expired = vi.fn()
    window.addEventListener("management:auth-expired", expired)
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ error: { message: "Forbidden" } }), { status: 403, headers: { "content-type": "application/json" } })))
    await expect(managementApi.accounts()).rejects.toMatchObject({ kind: "http", status: 403 })
    expect(expired).not.toHaveBeenCalled()
    window.removeEventListener("management:auth-expired", expired)
  })

  it("expires auth on a real 401", async () => {
    const expired = vi.fn()
    window.addEventListener("management:auth-expired", expired)
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ error: { message: "Unauthorized" } }), { status: 401, headers: { "content-type": "application/json" } })))
    await expect(managementApi.accounts()).rejects.toMatchObject({ kind: "http", status: 401 })
    expect(expired).toHaveBeenCalledTimes(1)
    window.removeEventListener("management:auth-expired", expired)
  })

  it("reports a network failure once as network telemetry", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")))
    const error = await managementApi.accounts().catch(value => value)
    expect(error).toMatchObject({ kind: "network", status: null })
    expect(notify.error).toHaveBeenCalledTimes(1)
    expect(telemetry.error).toHaveBeenCalledTimes(1)
  })

  it("does not notify or emit network-error telemetry for cancellation", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new DOMException("Aborted", "AbortError")))
    const error = await managementApi.accounts().catch(value => value)
    expect(error).toMatchObject({ kind: "aborted", status: null })
    expect(notify.error).not.toHaveBeenCalled()
    expect(telemetry.error).not.toHaveBeenCalled()
  })
})
