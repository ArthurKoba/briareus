import { nextTick } from "vue"
import { beforeEach, describe, expect, it, vi } from "vitest"

import type { SettingsState } from "@/shared/api/management"

const api = vi.hoisted(() => ({ settings: vi.fn() }))
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

function snapshot(revision: string, retention = 14): SettingsState {
  return {
    revision,
    management: { logging_enabled: true, logging_capture_payloads: false, logging_retention_days: retention, logging_max_records: 4000, maintenance_interval_minutes: 17 },
    terminal: { max_exec_timeout_seconds: 120, max_job_runtime_seconds: 600 },
    mcp: { call_timeout_seconds: 13 },
    github: { local_first_guidance: false, local_git_transport_enabled: true, remote_source_mutations_enabled: false },
    analysis: { idle_timeout_seconds: 111, source: "runtime" }, analysis_error: "",
  }
}

async function freshStore() {
  vi.resetModules()
  return (await import("@/shared/settings/store")).settingsStore
}

beforeEach(() => {
  vi.useFakeTimers()
  api.settings.mockReset()
  bus.subscribe.mockClear(); bus.handler = undefined
  if (bus.state) Object.assign(bus.state, { status: "idle", enabled: true, active: true })
})

describe("settings store realtime freshness", () => {
  it("accepts settings.updated and keeps the new revision without manual refresh", async () => {
    api.settings.mockResolvedValue(snapshot("r1"))
    const store = await freshStore()
    store.start(); store.setSessionActive(true); await Promise.resolve()
    bus.state!.status = "connected"; await nextTick()
    bus.handler?.({ topic: "management.events", type: "settings.updated", occurredAt: "", data: snapshot("r2", 30) })
    expect(store.state.value?.revision).toBe("r2")
    expect(store.state.value?.management.logging_retention_days).toBe(30)
    expect(store.state.synced).toBe(true)
    store.stop()
  })

  it("reconciles on reconnect even when the cached management snapshot is unrelated", async () => {
    api.settings.mockResolvedValueOnce(snapshot("r1")).mockResolvedValue(snapshot("r2", 31))
    const store = await freshStore()
    store.start(); store.setSessionActive(true); await Promise.resolve()
    bus.state!.status = "connected"; await nextTick(); await vi.runAllTimersAsync(); await Promise.resolve()
    expect(store.state.value?.revision).toBe("r2")
    expect(store.state.synced).toBe(true)
    store.stop()
  })

  it("marks the domain manual when transport is unavailable", async () => {
    api.settings.mockResolvedValue(snapshot("r1"))
    const store = await freshStore()
    store.start(); store.setSessionActive(true); await Promise.resolve()
    bus.state!.status = "connected"; await nextTick(); await vi.runAllTimersAsync(); await Promise.resolve()
    expect(store.state.synced).toBe(true)
    bus.state!.status = "reconnecting"; await nextTick()
    expect(store.state.synced).toBe(false)
    store.stop()
  })

  it("clears settings snapshot on logout", async () => {
    api.settings.mockResolvedValue(snapshot("r1"))
    const store = await freshStore()
    store.start(); store.setSessionActive(true); await Promise.resolve()
    store.setSessionActive(false)
    expect(store.state.value).toBeNull()
    expect(store.state.hydrated).toBe(false)
    store.stop()
  })
})
