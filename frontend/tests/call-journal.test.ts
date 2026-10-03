import { describe, expect, it } from "vitest"

import type { InvocationRecord } from "@/shared/api/management"
import { mergeCallJournal, enqueueCalls } from "@/pages/calls/model/call-journal"

function call(id: string, second: number, status: "success" | "error" = "success"): InvocationRecord {
  return { id, request_id: `req-${id}`, module: "github", tool: `tool-${id}`, account_id: "", provider: "github", status,
    duration_ms: second, error_type: "", arguments_json: "{}", result_json: "{}", error_message: "",
    occurred_at: `2026-10-03T20:00:${String(second).padStart(2,"0")}.000Z` }
}

describe("call journal rotation", () => {
  it("puts a realtime delta at the visible head and returns a new array reference", () => {
    const before = [call("old", 1)]
    const after = mergeCallJournal(before, [call("new", 2)])
    expect(after).not.toBe(before)
    expect(after.map(item => item.id)).toEqual(["new", "old"])
  })

  it("updates an existing invocation without duplicating it", () => {
    const after = mergeCallJournal([call("same", 1)], [{ ...call("same", 1), duration_ms: 42 }])
    expect(after).toHaveLength(1)
    expect(after[0].duration_ms).toBe(42)
  })

  it("sorts deterministically and evicts the oldest records at the bound", () => {
    const after = mergeCallJournal([call("one", 1), call("two", 2)], [call("three", 3)], 2)
    expect(after.map(item => item.id)).toEqual(["three", "two"])
  })

  it("deduplicates reconnect snapshots and batches", () => {
    const snapshot = [call("three", 3), call("two", 2)]
    const after = mergeCallJournal(snapshot, [call("three", 3), call("four", 4)])
    expect(after.map(item => item.id)).toEqual(["four", "three", "two"])
  })

  it("queues only unseen events while history is being read", () => {
    const visible = [call("two", 2), call("one", 1)]
    const pending = enqueueCalls([], [call("three", 3), call("two", 2)], visible)
    expect(pending.map(item => item.id)).toEqual(["three"])
    expect(enqueueCalls(pending, [call("four", 4), call("three", 3)], visible).map(item => item.id)).toEqual(["four", "three"])
  })
})
