import type { InvocationRecord } from "@/shared/api/admin"

export const CALL_CHUNK_SIZE = 100

function newestFirst(left: InvocationRecord, right: InvocationRecord): number {
  const time = right.occurred_at.localeCompare(left.occurred_at)
  return time || right.id.localeCompare(left.id)
}

/** Merge snapshots, REST chunks and deltas into one deterministic journal. */
export function mergeCallJournal(
  current: readonly InvocationRecord[],
  incoming: readonly InvocationRecord[],
  limit?: number,
): InvocationRecord[] {
  const byId = new Map<string, InvocationRecord>()
  for (const item of current) byId.set(item.id, item)
  for (const item of incoming) byId.set(item.id, item)
  const merged = [...byId.values()].sort(newestFirst)
  return limit === undefined ? merged : merged.slice(0, limit)
}

export function enqueueCalls(
  pending: readonly InvocationRecord[],
  incoming: readonly InvocationRecord[],
  visible: readonly InvocationRecord[],
  limit?: number,
): InvocationRecord[] {
  const visibleIds = new Set(visible.map(item => item.id))
  return mergeCallJournal(pending, incoming.filter(item => !visibleIds.has(item.id)), limit)
}
