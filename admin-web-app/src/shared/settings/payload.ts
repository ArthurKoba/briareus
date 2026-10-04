import type { SettingsState } from "@/shared/api/admin"

export interface SettingsUpdatePayload {
  expected_revision: string
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
  gitlab_local_first_guidance: boolean
  gitlab_local_git_transport_enabled: boolean
  gitlab_remote_source_mutations_enabled: boolean
  reverse_idle_timeout_seconds: number
}

export class IncompleteSettingsSnapshotError extends Error {
  constructor() {
    super("A complete version-control policy snapshot is required before saving settings")
    this.name = "IncompleteSettingsSnapshotError"
  }
}

export function settingsUpdatePayload(state: SettingsState, overrides: Partial<SettingsUpdatePayload> = {}): SettingsUpdatePayload {
  const githubPolicy = state.github
  const gitlabPolicy = state.gitlab
  // Never invent version-control policy values: unrelated settings saves must round-trip both
  // provider snapshots exactly as the server returned them.
  const policies = [githubPolicy, gitlabPolicy]
  if (policies.some(policy => !policy || [policy.local_first_guidance, policy.local_git_transport_enabled, policy.remote_source_mutations_enabled].some(value => typeof value !== "boolean"))) {
    throw new IncompleteSettingsSnapshotError()
  }
  const payload: SettingsUpdatePayload = {
    expected_revision: state.revision,
    logging_enabled: state.admin.logging_enabled,
    logging_capture_payloads: state.admin.logging_capture_payloads,
    logging_retention_days: state.admin.logging_retention_days,
    logging_max_records: state.admin.logging_max_records,
    maintenance_interval_minutes: state.admin.maintenance_interval_minutes,
    terminal_max_exec_timeout_seconds: state.terminal.max_exec_timeout_seconds,
    terminal_max_job_runtime_seconds: state.terminal.max_job_runtime_seconds,
    mcp_call_timeout_seconds: state.mcp.call_timeout_seconds,
    github_local_first_guidance: githubPolicy.local_first_guidance,
    github_local_git_transport_enabled: githubPolicy.local_git_transport_enabled,
    github_remote_source_mutations_enabled: githubPolicy.remote_source_mutations_enabled,
    gitlab_local_first_guidance: gitlabPolicy.local_first_guidance,
    gitlab_local_git_transport_enabled: gitlabPolicy.local_git_transport_enabled,
    gitlab_remote_source_mutations_enabled: gitlabPolicy.remote_source_mutations_enabled,
    reverse_idle_timeout_seconds: Number(state.analysis.idle_timeout_seconds ?? 900),
    ...overrides,
  }
  // Partial<T> permits undefined; do not let a caller erase a required flag.
  const requiredPolicyFlags = [
    payload.github_local_first_guidance,
    payload.github_local_git_transport_enabled,
    payload.github_remote_source_mutations_enabled,
    payload.gitlab_local_first_guidance,
    payload.gitlab_local_git_transport_enabled,
    payload.gitlab_remote_source_mutations_enabled,
  ]
  if (requiredPolicyFlags.some(value => typeof value !== "boolean")) {
    throw new IncompleteSettingsSnapshotError()
  }
  return payload
}
