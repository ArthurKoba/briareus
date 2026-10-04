import { flushPromises, mount } from "@vue/test-utils"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import DashboardPage from "@/pages/dashboard/DashboardPage.vue"
import type { DashboardState } from "@/shared/api/management"
import type { BusEvent } from "@/shared/events/bus"

const api = vi.hoisted(() => ({ dashboard: vi.fn() }))
const bus = vi.hoisted(() => ({
  handler: undefined as undefined | ((event: BusEvent) => void),
  state: { status: "connected", enabled: true },
  subscribe: vi.fn((_topic: string, handler: (event: BusEvent) => void) => { bus.handler = handler; return vi.fn() }),
}))
vi.mock("@/shared/api/management", () => ({ managementApi: api }))
vi.mock("@/shared/events/bus", () => ({ eventBus: { state: bus.state, subscribe: bus.subscribe } }))
vi.mock("vue-i18n", () => ({ useI18n: () => ({ t: (key: string) => key }) }))

function snapshot(tag: string, projects: number, stale = false): DashboardState {
  return {
    accounts: { total: projects, enabled: 0, by_provider: { github: 0 } },
    calls: { total: 0, errors: 0, error_rate: 0, average_duration_ms: 0 },
    oauth: { tracked: 0, active: 0 },
    workspace: { free_bytes: 0, size_bytes: 0, files: 0, tag },
    workspace_meta: { status: stale ? "error" : "ready", stale, updated_at: tag + "-workspace" },
    analysis: { projects, active_sessions: 0, workers: 0, running_workers: 0 },
    analysis_meta: { status: "ready", stale, updated_at: tag + "-analysis" },
  }
}

const mounted: ReturnType<typeof mount>[] = []
beforeEach(() => {
  api.dashboard.mockReset()
  bus.subscribe.mockClear()
  bus.handler = undefined
  bus.state.status = "connected"
  bus.state.enabled = true
})
afterEach(() => { for (const wrapper of mounted.splice(0)) wrapper.unmount() })

describe("Dashboard full realtime snapshot", () => {
  it("keeps a newer remote full snapshot over a slower REST bootstrap", async () => {
    let resolveRest!: (value: DashboardState) => void
    api.dashboard.mockImplementation(() => new Promise(resolve => { resolveRest = resolve }))
    const wrapper = mount(DashboardPage, { attachTo: document.body })
    mounted.push(wrapper)
    await flushPromises()
    expect(bus.subscribe).toHaveBeenCalledWith("system.metrics", expect.any(Function))

    bus.handler?.({ topic: "system.metrics", type: "snapshot", occurredAt: "", data: snapshot("remote", 0, true) })
    await flushPromises()
    expect(wrapper.text()).toContain("dashboard.staleData")
    expect(wrapper.text()).not.toContain("common.refresh")

    resolveRest(snapshot("older-rest", 7, false))
    await flushPromises()
    expect(wrapper.text()).not.toContain("7 dashboard.configured")
    expect(wrapper.text()).toContain("dashboard.staleData")
  })

  it("replaces freshness metadata atomically with every remote snapshot", async () => {
    api.dashboard.mockResolvedValue(snapshot("rest", 2, false))
    const wrapper = mount(DashboardPage, { attachTo: document.body })
    mounted.push(wrapper)
    await flushPromises()

    bus.handler?.({ topic: "system.metrics", type: "snapshot", occurredAt: "", data: snapshot("stale", 0, true) })
    await flushPromises()
    expect(wrapper.text()).toContain("dashboard.staleData")

    bus.handler?.({ topic: "system.metrics", type: "snapshot", occurredAt: "", data: snapshot("fresh", 0, false) })
    await flushPromises()
    expect(wrapper.text()).not.toContain("dashboard.staleData")
    expect(wrapper.text()).not.toContain("common.refresh")
  })
})
