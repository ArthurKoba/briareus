import { nextTick } from "vue"
import { beforeEach, describe, expect, it, vi } from "vitest"

import type { AccountRecord } from "@/shared/api/management"

const api = vi.hoisted(() => ({ accounts: vi.fn() }))
const bus = vi.hoisted(() => ({
  handler: undefined as undefined | ((event: { topic: string; type: string; occurredAt: string; data: unknown }) => void),
  state: null as null | { status: string; enabled: boolean; active: boolean },
  subscribe: vi.fn((_topic: string, handler: typeof bus.handler) => { bus.handler = handler; return vi.fn() }),
}))

vi.mock("@/shared/api/management", () => ({ managementApi: api }))
vi.mock("@/shared/events/bus", async () => {
  const { reactive } = await import("vue")
  bus.state = reactive({ status: "idle", enabled: true, active: true })
  return { eventBus: { state: bus.state, subscribe: bus.subscribe } }
})

function account(id: string, updatedAt: string, alias = id): AccountRecord {
  return {
    id, alias, provider: "github", auth_type: "github_token", base_url: "https://api.github.com",
    external_id: null, verify_tls: true, ca_cert_pem: null, enabled: true,
    created_at: "2026-10-04T08:00:00Z", updated_at: updatedAt,
  }
}

async function freshStore() {
  vi.resetModules()
  const module = await import("@/features/accounts/model/account-store")
  return module.accountStore
}

beforeEach(() => {
  vi.useFakeTimers()
  api.accounts.mockReset()
  bus.subscribe.mockClear()
  bus.handler = undefined
  if (bus.state) {
    bus.state.status = "idle"
    bus.state.enabled = true
    bus.state.active = true
  }
})

describe("account store realtime reconciliation", () => {
  it("applies create/update/delete deltas without manual refresh", async () => {
    api.accounts.mockResolvedValue({ accounts: [account("a", "2026-10-04T08:00:01Z")], count: 1 })
    const store = await freshStore()
    store.start()
    store.setSessionActive(true)
    await vi.runAllTimersAsync()
    await nextTick()
    expect(store.state.accounts.map(item => item.id)).toEqual(["a"])

    bus.state!.status = "connected"
    await nextTick()
    bus.handler?.({ topic: "management.events", type: "account.created", occurredAt: "", data: account("b", "2026-10-04T08:00:02Z") })
    expect(store.state.accounts.map(item => item.id).sort()).toEqual(["a", "b"])
    bus.handler?.({ topic: "management.events", type: "account.updated", occurredAt: "", data: account("b", "2026-10-04T08:00:03Z", "renamed") })
    expect(store.state.accounts.find(item => item.id === "b")?.alias).toBe("renamed")
    bus.handler?.({ topic: "management.events", type: "account.deleted", occurredAt: "", data: { id: "a", provider: "github" } })
    expect(store.state.accounts.map(item => item.id)).toEqual(["b"])
    store.stop()
  })

  it("does not let a stale REST response overwrite a newer event", async () => {
    let resolveRequest!: (value: { accounts: AccountRecord[]; count: number }) => void
    api.accounts.mockImplementationOnce(() => new Promise(resolve => { resolveRequest = resolve }))
    const store = await freshStore()
    store.start()
    store.setSessionActive(true)
    bus.state!.status = "connected"
    await nextTick()
    bus.handler?.({ topic: "management.events", type: "account.created", occurredAt: "", data: account("new", "2026-10-04T08:00:05Z") })
    resolveRequest({ accounts: [account("old", "2026-10-04T08:00:01Z")], count: 1 })
    await Promise.resolve()
    expect(store.state.accounts.some(item => item.id === "new")).toBe(true)
    store.stop()
  })

  it("reconciles after reconnect and hides live state until catch-up succeeds", async () => {
    api.accounts.mockResolvedValue({ accounts: [account("a", "2026-10-04T08:00:01Z")], count: 1 })
    const store = await freshStore()
    store.start()
    store.setSessionActive(true)
    await Promise.resolve()
    bus.state!.status = "connected"
    await nextTick()
    await vi.runAllTimersAsync()
    await Promise.resolve()
    expect(api.accounts.mock.calls.length).toBeGreaterThanOrEqual(2)
    expect(store.state.synced).toBe(true)
    bus.state!.status = "reconnecting"
    await nextTick()
    expect(store.state.synced).toBe(false)
    store.stop()
  })

  it("clears cached accounts on logout", async () => {
    api.accounts.mockResolvedValue({ accounts: [account("a", "2026-10-04T08:00:01Z")], count: 1 })
    const store = await freshStore()
    store.start()
    store.setSessionActive(true)
    await Promise.resolve()
    store.setSessionActive(false)
    expect(store.state.accounts).toEqual([])
    expect(store.state.hydrated).toBe(false)
    store.stop()
  })
})
