import { reactive, readonly, watch, type WatchStopHandle } from "vue"

import { adminApi, type SettingsState } from "@/shared/api/admin"
import { eventBus, type BusEvent } from "@/shared/events/bus"

const state = reactive({
  value: null as SettingsState | null,
  loading: false,
  error: "",
  hydrated: false,
  synced: false,
})

let started = false
let sessionActive = false
let unsubscribe: undefined | (() => void)
let stopStatus: WatchStopHandle | undefined
let requestRun = 0
let eventEpoch = 0
let reconcileTimer = 0

function liveTransport(): boolean {
  return sessionActive && eventBus.state.enabled && (eventBus.state.status === "connected" || eventBus.state.status === "mock")
}

function setSynced(value: boolean): void {
  state.synced = value && liveTransport() && state.hydrated
}

function accept(value: SettingsState): void {
  if (!sessionActive) return
  if (state.value?.revision !== value.revision) state.value = value
  state.hydrated = true
  setSynced(true)
}

function scheduleReconcile(delay = 25): void {
  window.clearTimeout(reconcileTimer)
  reconcileTimer = window.setTimeout(() => {
    reconcileTimer = 0
    void reconcile(false)
  }, delay)
}

function handle(event: BusEvent): void {
  if (!sessionActive) return
  eventEpoch += 1
  if (event.type === "settings.updated") {
    const data = event.data as Partial<SettingsState>
    if (typeof data.revision === "string" && data.admin && data.terminal && data.mcp && data.browser && data.github && data.analysis) {
      accept(data as SettingsState)
      return
    }
  }
  if (event.type === "snapshot") {
    setSynced(false)
    scheduleReconcile(0)
  }
}

async function reconcile(notifyErrors = false): Promise<SettingsState> {
  if (!sessionActive) throw new Error("Settings context is inactive")
  const run = ++requestRun
  const startedAtEpoch = eventEpoch
  state.loading = true
  state.error = ""
  try {
    const value = await adminApi.settings({ notifyErrors })
    if (run !== requestRun) return value
    if (startedAtEpoch !== eventEpoch) {
      scheduleReconcile(0)
      return value
    }
    accept(value)
    return value
  } catch (caught) {
    if (run === requestRun) {
      state.error = caught instanceof Error ? caught.message : "Unable to load settings"
      setSynced(false)
    }
    throw caught
  } finally {
    if (run === requestRun) state.loading = false
  }
}

function setSessionActive(active: boolean): void {
  sessionActive = active
  if (!active) {
    requestRun += 1
    window.clearTimeout(reconcileTimer)
    reconcileTimer = 0
    state.value = null
    state.loading = false
    state.hydrated = false
    state.synced = false
    state.error = ""
    return
  }
  void reconcile(false).catch(() => undefined)
}

function start(): void {
  if (started) return
  started = true
  unsubscribe = eventBus.subscribe("admin.events", handle)
  stopStatus = watch(
    () => [eventBus.state.status, eventBus.state.enabled, eventBus.state.active] as const,
    ([status], [previousStatus]) => {
      if (!liveTransport()) {
        setSynced(false)
        return
      }
      if (status === "connected" && previousStatus !== "connected") {
        setSynced(false)
        scheduleReconcile(0)
      } else {
        setSynced(true)
      }
    },
  )
}

function stop(): void {
  if (!started) return
  started = false
  unsubscribe?.()
  unsubscribe = undefined
  stopStatus?.()
  stopStatus = undefined
  window.clearTimeout(reconcileTimer)
  reconcileTimer = 0
}

export const settingsStore = {
  state: readonly(state),
  start,
  stop,
  setSessionActive,
  refresh: () => reconcile(true),
  ensure: () => reconcile(false),
  accept,
}
