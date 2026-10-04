import { describe, expect, it } from "vitest"

import type { SettingsState } from "@/shared/api/management"
import { settingsUpdatePayload } from "@/shared/settings/payload"

function snapshot(github: SettingsState["github"] = {
  local_first_guidance: false,
  local_git_transport_enabled: true,
  remote_source_mutations_enabled: false,
}): SettingsState {
  return {
    revision: "revision-1",
    management: { logging_enabled: true, logging_capture_payloads: false, logging_retention_days: 14, logging_max_records: 4000, maintenance_interval_minutes: 17 },
    terminal: { max_exec_timeout_seconds: 120, max_job_runtime_seconds: 600 },
    mcp: { call_timeout_seconds: 13 },
    github,
    analysis: { idle_timeout_seconds: 111, source: "runtime" },
    analysis_error: "",
  }
}

describe("settings round-trip preserves GitHub policy (#295)", () => {
  it.each([
    ["logging", { logging_enabled: false }],
    ["MCP timeout", { mcp_call_timeout_seconds: 23 }],
    ["Terminal timeout", { terminal_max_exec_timeout_seconds: 222 }],
    ["Analysis idle timeout", { reverse_idle_timeout_seconds: 333 }],
  ])("%s does not substitute server policy defaults", (_section, overrides) => {
    const state = snapshot()
    const before = structuredClone(state)
    const payload = settingsUpdatePayload(state, overrides)
    expect(payload).toMatchObject({
      expected_revision: "revision-1",
      ...overrides,
      github_local_first_guidance: false,
      github_local_git_transport_enabled: true,
      github_remote_source_mutations_enabled: false,
    })
    expect(state).toEqual(before)
  })

  it("round-trips every combination of policy booleans", () => {
    for (const guidance of [false, true]) for (const transport of [false, true]) for (const writes of [false, true]) {
      const payload = settingsUpdatePayload(snapshot({ local_first_guidance: guidance, local_git_transport_enabled: transport, remote_source_mutations_enabled: writes }))
      expect([payload.github_local_first_guidance, payload.github_local_git_transport_enabled, payload.github_remote_source_mutations_enabled]).toEqual([guidance, transport, writes])
    }
  })

  it("fails closed for incomplete policy snapshots", () => {
    const state = snapshot() as Omit<SettingsState, "github"> & { github?: SettingsState["github"] }
    delete state.github
    expect(() => settingsUpdatePayload(state as SettingsState)).toThrow()
  })

  it.each(["github_local_first_guidance", "github_local_git_transport_enabled", "github_remote_source_mutations_enabled"] as const)(
    "rejects undefined override of %s", (key) => {
      expect(() => settingsUpdatePayload(snapshot(), { [key]: undefined })).toThrow()
    },
  )
})
