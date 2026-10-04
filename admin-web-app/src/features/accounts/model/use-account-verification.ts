import { reactive } from "vue"

import type { AccountRecord } from "@/shared/api/admin"

type VerificationState =
  | { status: "idle" }
  | { status: "loading"; revision: string }
  | { status: "success"; revision: string; checkedAt: string }
  | { status: "error"; revision: string; message: string }

const idle: VerificationState = { status: "idle" }
const identity = (record: AccountRecord): string => JSON.stringify([record.provider, record.id])

/** UI-only outcomes for persisted records; this does not verify unsaved drafts. */
export function useAccountVerification(check: (record: AccountRecord) => Promise<unknown>) {
  const states = reactive<Record<string, VerificationState>>({})
  const pending = new Map<string, { revision: string; promise: Promise<boolean> }>()

  function stateFor(record: AccountRecord): VerificationState {
    const state = states[identity(record)]
    if (!state || state.status === "idle") return idle
    // A pending check locks this account, but a completed result certifies only
    // its captured persisted revision, never newer credentials/configuration.
    return state.status === "loading" || state.revision === record.updated_at ? state : idle
  }

  function verify(record: AccountRecord): Promise<boolean> {
    const key = identity(record)
    const revision = record.updated_at
    const existing = pending.get(key)
    if (existing) {
      return existing.promise.then(result => existing.revision === revision && result)
    }
    const snapshot = { ...record }
    states[key] = { status: "loading", revision }
    // Defer the call so the single-flight entry also covers synchronous throws.
    const promise = Promise.resolve().then(() => check(snapshot)).then(
      () => {
        states[key] = { status: "success", revision, checkedAt: new Date().toISOString() }
        return true
      },
      (caught: unknown) => {
        states[key] = { status: "error", revision, message: caught instanceof Error ? caught.message : String(caught) }
        return false
      },
    ).finally(() => pending.delete(key))
    pending.set(key, { revision, promise })
    return promise
  }

  return { stateFor, verify }
}
