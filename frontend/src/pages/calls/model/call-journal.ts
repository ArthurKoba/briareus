import type { InvocationRecord } from "@/shared/api/management"

export const CALL_JOURNAL_LIMIT = 500

function newestFirst(left: InvocationRecord, right: InvocationRecord): number {
  const time = right.occurred_at.localeCompare(left.occurred_at)
  return time || right.id.localeCompare(left.id)
}

/** Merge snapshots, REST responses and deltas into one deterministic bounded window. */
export function mergeCallJournal(
  current: readonly InvocationRecord[],
  incoming: readonly InvocationRecord[],
  limit = CALL_JOURNAL_LIMIT,
): InvocationRecord[] {
  const byId = new Map<string, InvocationRecord>()
  for (const item of current) byId.set(item.id, item)
  for (const item of incoming) byId.set(item.id, item)
  return [...byId.values()].sort(newestFirst).slice(0, limit)
}

export function enqueueCalls(
  pending: readonly InvocationRecord[],
  incoming: readonly InvocationRecord[],
  visible: readonly InvocationRecord[],
  limit = CALL_JOURNAL_LIMIT,
): InvocationRecord[] {
  const visibleIds = new Set(visible.map(item => item.id))
  return mergeCallJournal(pending, incoming.filter(item => !visibleIds.has(item.id)), limit)
}
