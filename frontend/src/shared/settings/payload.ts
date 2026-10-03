import type { SettingsState } from "@/shared/api/management"

export interface SettingsUpdatePayload {
  logging_enabled: boolean
  logging_capture_payloads: boolean
  logging_retention_days: number
  logging_max_records: number
  maintenance_interval_minutes: number
  terminal_max_exec_timeout_seconds: number
  terminal_max_job_runtime_seconds: number
  mcp_call_timeout_seconds: number
  github_local_first_guidance: boolean
  github_local_git_transport_enabled: boolean
  github_remote_source_mutations_enabled: boolean
  reverse_idle_timeout_seconds: number
}

export class IncompleteSettingsSnapshotError extends Error {
  constructor() {
    super("A complete GitHub policy snapshot is required before saving settings")
    this.name = "IncompleteSettingsSnapshotError"
  }
}

export function settingsUpdatePayload(state: SettingsState, overrides: Partial<SettingsUpdatePayload> = {}): SettingsUpdatePayload {
  const policy = state.github
  // The current backend PUT replaces all settings. Missing flags would activate
  // backend defaults, including re-enabling remote writes. Never invent them.
  if (!policy || [policy.local_first_guidance, policy.local_git_transport_enabled, policy.remote_source_mutations_enabled].some(value => typeof value !== "boolean")) {
    throw new IncompleteSettingsSnapshotError()
  }
  const payload: SettingsUpdatePayload = {
    logging_enabled: state.management.logging_enabled,
    logging_capture_payloads: state.management.logging_capture_payloads,
    logging_retention_days: state.management.logging_retention_days,
    logging_max_records: state.management.logging_max_records,
    maintenance_interval_minutes: state.management.maintenance_interval_minutes,
    terminal_max_exec_timeout_seconds: state.terminal.max_exec_timeout_seconds,
    terminal_max_job_runtime_seconds: state.terminal.max_job_runtime_seconds,
    mcp_call_timeout_seconds: state.mcp.call_timeout_seconds,
    github_local_first_guidance: policy.local_first_guidance,
    github_local_git_transport_enabled: policy.local_git_transport_enabled,
    github_remote_source_mutations_enabled: policy.remote_source_mutations_enabled,
    reverse_idle_timeout_seconds: Number(state.analysis.idle_timeout_seconds ?? 900),
    ...overrides,
  }
  // Partial<T> permits undefined; do not let a caller erase a required flag.
  if ([payload.github_local_first_guidance, payload.github_local_git_transport_enabled, payload.github_remote_source_mutations_enabled].some(value => typeof value !== "boolean")) {
    throw new IncompleteSettingsSnapshotError()
  }
  return payload
}
