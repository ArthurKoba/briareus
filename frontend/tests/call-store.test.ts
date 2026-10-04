import { nextTick } from "vue"
import { beforeEach, describe, expect, it, vi } from "vitest"

import type { InvocationRecord } from "@/shared/api/management"

const api = vi.hoisted(() => ({ calls: vi.fn() }))
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

function call(id: string, second: number): InvocationRecord {
  return { id, request_id: `req-${id}`, module: "web", tool: `tool-${id}`, account_id: "", provider: "web", status: "success",
    duration_ms: second, error_type: "", arguments_json: "{}", result_json: "{}", error_message: "",
    occurred_at: `2026-10-04T09:00:${String(second).padStart(2, "0")}.000Z` }
}

async function freshStore() {
  vi.resetModules()
  return (await import("@/pages/calls/model/call-store")).callStore
}

beforeEach(() => {
  vi.useFakeTimers()
  api.calls.mockReset()
  bus.subscribe.mockClear()
  bus.handler = undefined
  if (bus.state) Object.assign(bus.state, { status: "idle", enabled: true, active: true })
})

describe("call store app-scoped freshness", () => {
  it("keeps a hot journal and applies realtime batches while the page is away", async () => {
    api.calls.mockResolvedValue({ events: [call("old", 1)], count: 1 })
    const store = await freshStore()
    store.start(); store.setSessionActive(true)
    await Promise.resolve()
    bus.state!.status = "connected"
    await nextTick(); await vi.runAllTimersAsync(); await Promise.resolve()
    bus.handler?.({ topic: "mcp.calls", type: "batch", occurredAt: "", data: { events: [call("new", 2)], count: 1 } })
    expect(store.state.rows.map(item => item.id)).toEqual(["new", "old"])
    expect(store.state.synced).toBe(true)
    store.stop()
  })

  it("queues events only while history is being read and merges them on leave", async () => {
    api.calls.mockResolvedValue({ events: [call("old", 1)], count: 1 })
    const store = await freshStore()
    store.start(); store.setSessionActive(true); await Promise.resolve()
    store.setFollowingLive(false)
    bus.handler?.({ topic: "mcp.calls", type: "batch", occurredAt: "", data: { events: [call("new", 2)], count: 1 } })
    expect(store.state.rows.map(item => item.id)).toEqual(["old"])
    expect(store.state.pending.map(item => item.id)).toEqual(["new"])
    store.leaveView()
    expect(store.state.rows.map(item => item.id)).toEqual(["new", "old"])
    expect(store.state.pending).toEqual([])
    store.stop()
  })

  it("reconciles missed deletes after reconnect instead of preserving stale rows", async () => {
    api.calls.mockResolvedValueOnce({ events: [call("a", 1), call("b", 2)], count: 2 })
      .mockResolvedValue({ events: [call("b", 2)], count: 1 })
    const store = await freshStore()
    store.start(); store.setSessionActive(true); await Promise.resolve()
    expect(store.state.rows.map(item => item.id).sort()).toEqual(["a", "b"])
    bus.state!.status = "connected"
    await nextTick(); await vi.runAllTimersAsync(); await Promise.resolve()
    expect(store.state.rows.map(item => item.id)).toEqual(["b"])
    store.stop()
  })

  it("clears journal and pending data on logout", async () => {
    api.calls.mockResolvedValue({ events: [call("a", 1)], count: 1 })
    const store = await freshStore()
    store.start(); store.setSessionActive(true); await Promise.resolve()
    store.setSessionActive(false)
    expect(store.state.rows).toEqual([])
    expect(store.state.pending).toEqual([])
    expect(store.state.hydrated).toBe(false)
    store.stop()
  })
})
