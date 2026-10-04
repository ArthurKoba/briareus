import { reactive, readonly, watch, type WatchStopHandle } from "vue"

import { adminApi, type AccountRecord } from "@/shared/api/admin"
import { eventBus, type BusEvent } from "@/shared/events/bus"

const state = reactive({
  accounts: [] as AccountRecord[],
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

const identity = (provider: string, id: string) => `${provider}:${id}`
const recordIdentity = (record: AccountRecord) => identity(record.provider, record.id)

function liveTransport(): boolean {
  return sessionActive && eventBus.state.enabled && (eventBus.state.status === "connected" || eventBus.state.status === "mock")
}

function setSynced(value: boolean): void {
  state.synced = value && liveTransport() && state.hydrated
}

function upsert(record: AccountRecord): void {
  const key = recordIdentity(record)
  const current = state.accounts.find(item => recordIdentity(item) === key)
  if (current && current.updated_at > record.updated_at) return
  state.accounts = current
    ? state.accounts.map(item => recordIdentity(item) === key ? record : item)
    : [record, ...state.accounts]
}

function remove(provider: string, id: string): void {
  const key = identity(provider, id)
  state.accounts = state.accounts.filter(item => recordIdentity(item) !== key)
}

function scheduleReconcile(delay = 25): void {
  window.clearTimeout(reconcileTimer)
  reconcileTimer = window.setTimeout(() => {
    reconcileTimer = 0
    void reconcile()
  }, delay)
}

function handle(event: BusEvent): void {
  eventEpoch += 1
  if (event.type === "snapshot") {
    setSynced(false)
    scheduleReconcile(0)
    return
  }
  const data = event.data && typeof event.data === "object" ? event.data as Record<string, unknown> : {}
  if (event.type === "account.created" || event.type === "account.updated") {
    if (typeof data.id === "string" && typeof data.provider === "string") upsert(data as unknown as AccountRecord)
  } else if (event.type === "account.deleted") {
    if (typeof data.id === "string" && typeof data.provider === "string") remove(data.provider, data.id)
    else if (typeof data.id === "string") state.accounts = state.accounts.filter(item => item.id !== data.id)
  }
  setSynced(true)
}

async function reconcile(notifyErrors = false): Promise<void> {
  const run = ++requestRun
  const startedAtEpoch = eventEpoch
  state.loading = true
  state.error = ""
  try {
    const response = await adminApi.accounts({ notifyErrors })
    if (run !== requestRun) return
    if (startedAtEpoch !== eventEpoch) {
      scheduleReconcile(0)
      return
    }
    state.accounts = response.accounts
    state.hydrated = true
    setSynced(true)
  } catch (caught) {
    if (run !== requestRun) return
    state.error = caught instanceof Error ? caught.message : "Unable to load accounts"
    setSynced(false)
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
    state.accounts = []
    state.hydrated = false
    state.synced = false
    state.error = ""
    return
  }
  void reconcile().catch(() => undefined)
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

export const accountStore = {
  state: readonly(state),
  start,
  stop,
  setSessionActive,
  refresh: () => reconcile(true),
  upsert,
  remove,
}
