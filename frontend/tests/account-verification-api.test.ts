import { afterEach, describe, expect, it, vi } from "vitest"

import { managementApi, type AccountRecord } from "@/shared/api/management"

const notify = vi.hoisted(() => ({ error: vi.fn() }))
vi.mock("@/shared/notifications/bus", () => ({ notifications: notify }))
vi.mock("@/shared/config/runtime", () => ({ runtimeConfig: { preview: false } }))
vi.mock("@/shared/telemetry/client", () => ({ frontendTelemetry: { api: vi.fn(), error: vi.fn() } }))
vi.mock("@/shared/i18n", () => ({ i18n: { global: { t: (key: string) => key } } }))

const record: AccountRecord = {
  id: "test-id", provider: "github", alias: "fixture", auth_type: "github_token",
  base_url: "", external_id: null, verify_tls: true, ca_cert_pem: null, enabled: true,
  created_at: "2026-10-03T00:00:00Z", updated_at: "2026-10-03T00:00:00Z",
}

afterEach(() => vi.unstubAllGlobals())

describe("verification error ownership", () => {
  it("returns structured HTTP errors to the inline UI without a transport toast", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(
      JSON.stringify({ error: { code: "unavailable", message: "Provider unavailable" } }),
      { status: 502, headers: { "content-type": "application/json" } },
    )))
    await expect(managementApi.verifyAccount(record)).rejects.toThrow("Provider unavailable")
    expect(notify.error).not.toHaveBeenCalled()
  })

  it("returns network failures to the inline UI without a transport toast", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")))
    await expect(managementApi.verifyAccount(record)).rejects.toThrow("Failed to fetch")
    expect(notify.error).not.toHaveBeenCalled()
  })

  it("does not disable normal error reporting for unrelated API calls", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")))
    await expect(managementApi.accounts()).rejects.toThrow("Failed to fetch")
    expect(notify.error).toHaveBeenCalledTimes(1)
  })
})
