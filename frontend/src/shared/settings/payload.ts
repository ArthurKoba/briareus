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
  reverse_idle_timeout_seconds: number
}

export function settingsUpdatePayload(state: SettingsState, overrides: Partial<SettingsUpdatePayload> = {}): SettingsUpdatePayload {
  return {
    logging_enabled: state.management.logging_enabled,
    logging_capture_payloads: state.management.logging_capture_payloads,
    logging_retention_days: state.management.logging_retention_days,
    logging_max_records: state.management.logging_max_records,
    maintenance_interval_minutes: state.management.maintenance_interval_minutes,
    terminal_max_exec_timeout_seconds: state.terminal.max_exec_timeout_seconds,
    terminal_max_job_runtime_seconds: state.terminal.max_job_runtime_seconds,
    mcp_call_timeout_seconds: state.mcp.call_timeout_seconds,
    reverse_idle_timeout_seconds: Number(state.analysis.idle_timeout_seconds ?? 900),
    ...overrides,
  }
}
