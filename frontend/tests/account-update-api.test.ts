import { afterEach, describe, expect, it, vi } from "vitest"

import { managementApi, type AccountRecord } from "@/shared/api/management"

const notify = vi.hoisted(() => ({ error: vi.fn() }))
vi.mock("@/shared/notifications/bus", () => ({ notifications: notify }))
vi.mock("@/shared/config/runtime", () => ({ runtimeConfig: { preview: false } }))
vi.mock("@/shared/telemetry/client", () => ({ frontendTelemetry: { api: vi.fn(), error: vi.fn() } }))
vi.mock("@/shared/i18n", () => ({ i18n: { global: { t: (key: string) => key } } }))

const record: AccountRecord = {
  id: "account-1",
  provider: "gitlab",
  alias: "existing",
  auth_type: "private_token",
  base_url: "https://gitlab.example.test",
  external_id: null,
  verify_tls: true,
  ca_cert_pem: null,
  enabled: true,
  created_at: "2026-10-03T00:00:00Z",
  updated_at: "2026-10-03T01:02:03.000Z",
}

afterEach(() => vi.unstubAllGlobals())

describe("account update concurrency", () => {
  it("sends the persisted updated_at as the optimistic concurrency precondition", async () => {
    const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify(record), {
      status: 200,
      headers: { "content-type": "application/json" },
    }))
    vi.stubGlobal("fetch", fetch)

    await managementApi.updateAccount(record, {
      alias: "renamed",
      provider: "gitlab",
      auth_type: "private_token",
      base_url: record.base_url,
      verify_tls: true,
      enabled: true,
      credential: "",
    })

    expect(fetch).toHaveBeenCalledTimes(1)
    const [, init] = fetch.mock.calls[0]
    expect(JSON.parse(String(init.body))).toMatchObject({
      alias: "renamed",
      expected_updated_at: record.updated_at,
    })
  })
})
