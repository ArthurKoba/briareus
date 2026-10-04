import { reactive, readonly, watch, type WatchStopHandle } from "vue"

import { managementApi, type InvocationRecord } from "@/shared/api/management"
import { eventBus, type BusEvent } from "@/shared/events/bus"
import { CALL_JOURNAL_LIMIT, enqueueCalls, mergeCallJournal } from "./call-journal"

const state = reactive({
  rows: [] as InvocationRecord[],
  pending: [] as InvocationRecord[],
  loading: false,
  error: "",
  hydrated: false,
  synced: false,
  followingLive: true,
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

function acceptIncoming(items: InvocationRecord[]): void {
  if (!items.length) return
  if (state.followingLive) state.rows = mergeCallJournal(state.rows, items)
  else state.pending = enqueueCalls(state.pending, items, state.rows)
}

function scheduleReconcile(delay = 25): void {
  window.clearTimeout(reconcileTimer)
  reconcileTimer = window.setTimeout(() => {
    reconcileTimer = 0
    void reconcile(false)
  }, delay)
}

function handle(event: BusEvent): void {
  eventEpoch += 1
  if (event.type === "snapshot") {
    const payload = event.data as { events?: InvocationRecord[] }
    acceptIncoming(payload.events ?? [])
    setSynced(false)
    scheduleReconcile(0)
    return
  }
  if (event.type === "batch") {
    const payload = event.data as { events?: InvocationRecord[] }
    acceptIncoming(payload.events ?? [])
  } else if (event.type === "item") {
    acceptIncoming([event.data as InvocationRecord])
  }
  setSynced(true)
}

async function reconcile(notifyErrors = false): Promise<void> {
  const run = ++requestRun
  const startedAtEpoch = eventEpoch
  state.loading = true
  state.error = ""
  try {
    const calls = await managementApi.calls(CALL_JOURNAL_LIMIT, { notifyErrors })
    if (run !== requestRun) return
    if (startedAtEpoch !== eventEpoch) {
      scheduleReconcile(0)
      return
    }
    state.rows = mergeCallJournal([], calls.events)
    state.pending = []
    state.hydrated = true
    setSynced(true)
  } catch (caught) {
    if (run !== requestRun) return
    state.error = caught instanceof Error ? caught.message : "Unable to load calls"
    setSynced(false)
    throw caught
  } finally {
    if (run === requestRun) state.loading = false
  }
}

function setFollowingLive(value: boolean): void {
  state.followingLive = value
}

function applyPending(): void {
  state.rows = mergeCallJournal(state.rows, state.pending)
  state.pending = []
  state.followingLive = true
}

function leaveView(): void {
  applyPending()
}

function remove(id: string): void {
  state.rows = state.rows.filter(item => item.id !== id)
  state.pending = state.pending.filter(item => item.id !== id)
}

function clear(): void {
  state.rows = []
  state.pending = []
}

function setSessionActive(active: boolean): void {
  sessionActive = active
  if (!active) {
    requestRun += 1
    window.clearTimeout(reconcileTimer)
    reconcileTimer = 0
    clear()
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
  unsubscribe = eventBus.subscribe("mcp.calls", handle)
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

export const callStore = {
  state: readonly(state),
  start,
  stop,
  setSessionActive,
  refresh: () => reconcile(true),
  ensure: () => reconcile(false),
  setFollowingLive,
  applyPending,
  leaveView,
  remove,
  clear,
}
