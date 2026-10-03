import { describe, expect, test } from "bun:test"
import { settingsUpdatePayload } from "../src/shared/settings/payload.ts"

function snapshot(github = {
  local_first_guidance: false,
  local_git_transport_enabled: true,
  remote_source_mutations_enabled: false,
}) {
  return {
    management: { logging_enabled: true, logging_capture_payloads: false, logging_retention_days: 14, logging_max_records: 4000, maintenance_interval_minutes: 17 },
    terminal: { max_exec_timeout_seconds: 120, max_job_runtime_seconds: 600 },
    mcp: { call_timeout_seconds: 13 },
    github,
    analysis: { idle_timeout_seconds: 111, source: "runtime" },
    analysis_error: "",
  }
}

function expectPolicy(payload, policy) {
  expect(payload.github_local_first_guidance).toBe(policy.local_first_guidance)
  expect(payload.github_local_git_transport_enabled).toBe(policy.local_git_transport_enabled)
  expect(payload.github_remote_source_mutations_enabled).toBe(policy.remote_source_mutations_enabled)
}

describe("settings round-trip preserves GitHub policy (#295)", () => {
  test.each([
    ["logging", { logging_enabled: false }],
    ["MCP timeout", { mcp_call_timeout_seconds: 23 }],
    ["Terminal timeout", { terminal_max_exec_timeout_seconds: 222 }],
    ["Analysis idle timeout", { reverse_idle_timeout_seconds: 333 }],
  ])("%s does not substitute server policy defaults", (_section, overrides) => {
    const state = snapshot()
    const before = structuredClone(state)
    const payload = settingsUpdatePayload(state, overrides)
    expectPolicy(payload, state.github)
    expect(payload).toMatchObject(overrides)
    expect(state).toEqual(before)
  })

  test("round-trips every combination of boolean policy values", () => {
    for (const guidance of [false, true]) for (const transport of [false, true]) for (const writes of [false, true]) {
      const state = snapshot({ local_first_guidance: guidance, local_git_transport_enabled: transport, remote_source_mutations_enabled: writes })
      expectPolicy(settingsUpdatePayload(state), state.github)
    }
  })

  test.each([undefined, null, {}, { local_first_guidance: true }, { local_first_guidance: false, local_git_transport_enabled: true, remote_source_mutations_enabled: "false" }])(
    "fails closed for an incomplete policy snapshot: %p", (github) => {
      const state = snapshot()
      state.github = github
      expect(() => settingsUpdatePayload(state)).toThrow()
    },
  )

  test("an explicit policy edit is preserved without changing other fields", () => {
    const state = snapshot()
    const oldPayload = settingsUpdatePayload(state)
    const next = settingsUpdatePayload(state, { github_local_first_guidance: true })
    expect(next).toEqual({ ...oldPayload, github_local_first_guidance: true })
    expect(state.github.local_first_guidance).toBe(false)
  })

  test("preserves zero idle timeout, false flags and all unrelated current fields", () => {
    const state = snapshot()
    state.analysis.idle_timeout_seconds = 0
    const payload = settingsUpdatePayload(state, { logging_max_records: 2000 })
    expect(payload.reverse_idle_timeout_seconds).toBe(0)
    expect(payload.logging_capture_payloads).toBe(false)
    expect(payload.terminal_max_job_runtime_seconds).toBe(600)
    expect(payload.mcp_call_timeout_seconds).toBe(13)
    expect(payload.maintenance_interval_minutes).toBe(17)
    expectPolicy(payload, state.github)
  })
})

test.each(["github_local_first_guidance", "github_local_git_transport_enabled", "github_remote_source_mutations_enabled"])(
  "rejects an undefined override of %s rather than omitting it from JSON", (key) => {
    expect(() => settingsUpdatePayload(snapshot(), { [key]: undefined })).toThrow()
  },
)
