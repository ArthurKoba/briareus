import { reactive, readonly, watch, type WatchStopHandle } from "vue"

import { managementApi, type InvocationQuery, type InvocationRecord } from "@/shared/api/management"
import { eventBus, type BusEvent } from "@/shared/events/bus"
import { CALL_CHUNK_SIZE, enqueueCalls, mergeCallJournal } from "./call-journal"

export type CallViewMode = "infinite" | "pagination"
export interface CallFilters {
  module: string
  tool: string
  provider: string
  account_id: string
  status: "" | "success" | "error"
  search: string
}

const RECENT_CACHE_SIZE = 100
const emptyFilters = (): CallFilters => ({ module: "", tool: "", provider: "", account_id: "", status: "", search: "" })

const state = reactive({
  recent: [] as InvocationRecord[],
  recentHydrated: false,
  recentLoading: false,
  rows: [] as InvocationRecord[],
  pending: [] as InvocationRecord[],
  loading: false,
  loadingMore: false,
  error: "",
  hydrated: false,
  synced: false,
  followingLive: true,
  nextCursor: "",
  hasMore: false,
  total: 0,
  mode: "infinite" as CallViewMode,
  filters: emptyFilters(),
  pageRows: [] as InvocationRecord[],
  page: 1,
  pageSize: 50,
  pageTotal: 0,
  pageLoading: false,
  pageHydrated: false,
  relativeTime: false,
})

let started = false
let sessionActive = false
let unsubscribe: undefined | (() => void)
let stopStatus: WatchStopHandle | undefined
let requestRun = 0
let recentRun = 0
let pageRun = 0
let eventEpoch = 0
let reconcileTimer = 0

function liveTransport(): boolean {
  return sessionActive && eventBus.state.enabled && (eventBus.state.status === "connected" || eventBus.state.status === "mock")
}

function setSynced(value: boolean): void {
  const explorerHydrated = state.mode === "pagination" ? state.pageHydrated : state.hydrated
  state.synced = value && liveTransport() && state.recentHydrated && explorerHydrated
}

function queryFilters(extra: InvocationQuery = {}): InvocationQuery {
  return {
    ...extra,
    ...(state.filters.module ? { module: state.filters.module } : {}),
    ...(state.filters.tool ? { tool: state.filters.tool } : {}),
    ...(state.filters.provider ? { provider: state.filters.provider } : {}),
    ...(state.filters.account_id ? { account_id: state.filters.account_id } : {}),
    ...(state.filters.status ? { status: state.filters.status } : {}),
    ...(state.filters.search ? { search: state.filters.search } : {}),
  }
}

function matchesFilters(item: InvocationRecord): boolean {
  if (state.filters.module && item.module !== state.filters.module) return false
  if (state.filters.tool && item.tool !== state.filters.tool) return false
  if (state.filters.provider && item.provider !== state.filters.provider) return false
  if (state.filters.account_id && item.account_id !== state.filters.account_id) return false
  if (state.filters.status && item.status !== state.filters.status) return false
  const search = state.filters.search.trim().toLocaleLowerCase()
  if (!search) return true
  return [item.module, item.tool, item.request_id, item.provider, item.account_id]
    .some(value => value.toLocaleLowerCase().includes(search))
}

function acceptIncoming(items: InvocationRecord[]): void {
  if (!items.length) return
  state.recent = mergeCallJournal(state.recent, items, RECENT_CACHE_SIZE)
  state.recentHydrated = true

  const relevant = items.filter(matchesFilters)
  if (!relevant.length) {
    setSynced(true)
    return
  }
  const known = new Set(state.rows.map(item => item.id))
  const unseen = relevant.filter(item => !known.has(item.id)).length
  if (state.followingLive) state.rows = mergeCallJournal(state.rows, relevant)
  else state.pending = enqueueCalls(state.pending, relevant, state.rows)
  state.total += unseen

  if (state.page === 1) {
    const pageKnown = new Set(state.pageRows.map(item => item.id))
    const pageUnseen = relevant.filter(item => !pageKnown.has(item.id)).length
    state.pageRows = mergeCallJournal(state.pageRows, relevant, state.pageSize)
    state.pageTotal += pageUnseen
  }
  setSynced(true)
}

function scheduleReconcile(delay = 25): void {
  window.clearTimeout(reconcileTimer)
  reconcileTimer = window.setTimeout(() => {
    reconcileTimer = 0
    void reconcile(false)
    if (state.mode === "pagination") void loadPage(state.page, false)
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
}

async function reconcileRecent(): Promise<void> {
  const run = ++recentRun
  const startedAtEpoch = eventEpoch
  state.recentLoading = true
  try {
    const page = await managementApi.calls({ limit: RECENT_CACHE_SIZE }, { notifyErrors: false })
    if (run !== recentRun) return
    state.recent = startedAtEpoch === eventEpoch
      ? mergeCallJournal([], page.events, RECENT_CACHE_SIZE)
      : mergeCallJournal(page.events, state.recent, RECENT_CACHE_SIZE)
    state.recentHydrated = true
    setSynced(true)
  } catch {
    if (run === recentRun) setSynced(false)
  } finally {
    if (run === recentRun) state.recentLoading = false
  }
}

async function reconcile(notifyErrors = false): Promise<void> {
  const run = ++requestRun
  const startedAtEpoch = eventEpoch
  state.loading = true
  state.error = ""
  try {
    const calls = await managementApi.calls(queryFilters({ limit: CALL_CHUNK_SIZE }), { notifyErrors })
    if (run !== requestRun) return
    if (startedAtEpoch !== eventEpoch) {
      scheduleReconcile(0)
      return
    }
    state.rows = mergeCallJournal([], calls.events)
    state.pending = []
    state.nextCursor = calls.next_cursor
    state.hasMore = calls.has_more
    state.total = calls.total
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

async function loadMore(): Promise<void> {
  if (state.loading || state.loadingMore || !state.hasMore || !state.nextCursor) return
  state.loadingMore = true
  try {
    const page = await managementApi.calls(queryFilters({ limit: CALL_CHUNK_SIZE, cursor: state.nextCursor }), { notifyErrors: false })
    state.rows = mergeCallJournal(state.rows, page.events)
    state.nextCursor = page.next_cursor
    state.hasMore = page.has_more
    state.total = page.total
  } catch (caught) {
    state.error = caught instanceof Error ? caught.message : "Unable to load older calls"
  } finally {
    state.loadingMore = false
  }
}

async function loadPage(page = state.page, notifyErrors = false): Promise<void> {
  const normalizedPage = Math.max(1, page)
  const run = ++pageRun
  const startedAtEpoch = eventEpoch
  state.pageLoading = true
  state.error = ""
  try {
    const result = await managementApi.calls(queryFilters({
      limit: state.pageSize,
      offset: (normalizedPage - 1) * state.pageSize,
    }), { notifyErrors })
    if (run !== pageRun) return
    state.page = normalizedPage
    if (normalizedPage === 1 && startedAtEpoch !== eventEpoch) {
      state.pageRows = mergeCallJournal(result.events, state.pageRows, state.pageSize)
      state.pageTotal = Math.max(result.total, state.pageTotal)
    } else {
      state.pageRows = result.events
      state.pageTotal = result.total
    }
    state.pageHydrated = true
    setSynced(true)
  } catch (caught) {
    if (run === pageRun) {
      state.error = caught instanceof Error ? caught.message : "Unable to load calls page"
      state.pageHydrated = false
      setSynced(false)
    }
    throw caught
  } finally {
    if (run === pageRun) state.pageLoading = false
  }
}

async function setMode(mode: CallViewMode): Promise<void> {
  if (state.mode === mode) return
  state.mode = mode
  if (mode === "pagination") {
    state.pageHydrated = false
    setSynced(false)
    await loadPage(1, false)
  }
  else if (!state.hydrated || !state.rows.length) await reconcile(false)
}

async function setFilters(filters: Partial<CallFilters>): Promise<void> {
  state.filters = { ...state.filters, ...filters }
  state.rows = []
  state.pending = []
  state.hydrated = false
  state.nextCursor = ""
  state.hasMore = false
  state.total = 0
  state.page = 1
  state.pageRows = []
  state.pageTotal = 0
  state.pageHydrated = false
  setSynced(false)
  if (state.mode === "pagination") await loadPage(1, false)
  else await reconcile(false)
}

async function setPage(page: number): Promise<void> { await loadPage(page, true) }
async function setPageSize(pageSize: number): Promise<void> {
  state.pageSize = Math.max(1, pageSize)
  await loadPage(1, true)
}

function setRelativeTime(enabled: boolean): void { state.relativeTime = enabled }
function setFollowingLive(value: boolean): void { state.followingLive = value }
function applyPending(): void {
  state.rows = mergeCallJournal(state.rows, state.pending)
  state.pending = []
  state.followingLive = true
}
function leaveView(): void { applyPending() }

function remove(id: string): void {
  const existed = state.rows.some(item => item.id === id)
  state.recent = state.recent.filter(item => item.id !== id)
  state.rows = state.rows.filter(item => item.id !== id)
  state.pending = state.pending.filter(item => item.id !== id)
  state.pageRows = state.pageRows.filter(item => item.id !== id)
  if (existed) state.total = Math.max(0, state.total - 1)
  state.pageTotal = Math.max(0, state.pageTotal - 1)
}

function clear(): void {
  state.recent = []
  state.rows = []
  state.pending = []
  state.pageRows = []
  state.pageHydrated = false
  state.nextCursor = ""
  state.hasMore = false
  state.total = 0
  state.pageTotal = 0
}

function setSessionActive(active: boolean): void {
  sessionActive = active
  if (!active) {
    requestRun += 1
    recentRun += 1
    pageRun += 1
    window.clearTimeout(reconcileTimer)
    reconcileTimer = 0
    clear()
    state.hydrated = false
    state.recentHydrated = false
    state.recentLoading = false
    state.pageHydrated = false
    state.synced = false
    state.error = ""
    return
  }
  void reconcileRecent()
  void reconcile(false).catch(() => undefined)
  if (state.mode === "pagination") void loadPage(state.page, false).catch(() => undefined)
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
        void reconcileRecent()
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
  refresh: () => state.mode === "pagination" ? loadPage(state.page, true) : reconcile(true),
  ensure: () => reconcile(false),
  loadMore,
  setMode,
  setFilters,
  setPage,
  setPageSize,
  setRelativeTime,
  setFollowingLive,
  applyPending,
  leaveView,
  remove,
  clear,
}
