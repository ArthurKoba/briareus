/** Presentation-level error categories, independent of still-unapproved C1-B routes. */
export type UiErrorKind = "conflict" | "unauthorized" | "forbidden" | "unavailable" | "invalid" | "uncertain" | "unknown"
export interface UiError { kind: UiErrorKind; message: string; code: string }

/**
 * ONLY verified pre-HTTP authority failures are safe to treat as denied.
 * A broad /owner_mismatch$/ match is UNSAFE: a server can commit a Team or
 * Project transfer and then fail response owner validation. In that case the
 * write outcome is UNCERTAIN and a fresh idempotency key must stay blocked.
 */
const verifiedPreflightFailures = new Set([
  "verified_permission_revision_changed", "team_action_permission_changed",
  "project_transfer_permission_changed", "reassign_project_decision_changed",
  "verified_operator_required", "operator_scope_required",
  "team_resource_owner_mismatch", "team_resource_permission_revoked",
  "project_resource_permission_revoked", "project_team_resource_permission_revoked",
  "team_access_revision_mismatch", "project_access_revision_mismatch",
  "project_team_owner_decision_mismatch", "project_personal_owner_decision_mismatch",
  "agent_manage_revoked", "agent_scope_mismatch",
  "session_decision_changed", "approval_permission_revoked",
  "project_permission_revoked", "project_decision_scope_mismatch",
  "team_decision_scope_mismatch", "team_resource_scope_invalid",
  "project_resource_scope_invalid", "foreign_team_inheritance_rejected",
])

/** Only known status and opaque code are retained; never display server payloads or secrets. */
export function normalizeUiError(error: unknown, phase: "read" | "mutation" = "read"): UiError {
  const data = error && typeof error === "object" ? error as Record<string, unknown> : {}
  const envelope = data.error && typeof data.error === "object" ? data.error as Record<string, unknown> : {}
  const status = typeof data.status === "number" ? data.status : typeof envelope.status === "number" ? envelope.status : null
  const code = typeof data.code === "string" ? data.code : typeof envelope.code === "string" ? envelope.code : ""
  if (data.name === "DraftContractError") {
    // Permission/ownership preflight failures are known to happen BEFORE an
    // outbound mutation. Discard the stale context instead of claiming that
    // a write might have committed or enabling its retry with old privileges.
    if (verifiedPreflightFailures.has(code)) {
      return { kind: "forbidden", code, message: "permissionChanged" }
    }
    // A malformed response AFTER a mutation can mean a committed write.
    // No synthetic success, rollback claim or automatic new idempotency key.
    return phase === "mutation"
      ? { kind: "uncertain", code, message: "outcomeUncertain" }
      : { kind: "unavailable", code, message: "contractPending" }
  }
  if (code === "contract_not_available" || code.endsWith("_route_missing")) {
    return { kind: "unavailable", code, message: "contractPending" }
  }
  if (status === 401) return { kind: "unauthorized", code, message: "authenticationExpired" }
  // A future Authorization-owned schema migration may temporarily keep
  // verified Admin callers unavailable. 503 is NOT evidence migrations ran;
  // never trigger a client-side migration, fake readiness or replay a write.
  if (status === 503 && phase === "read")return {kind:"unavailable",code:"service_unavailable",message:"serviceUnavailableOrUpgrading"}
  if (status === 429) return { kind: "unavailable", code, message: "rateLimited" }
  if (status === 403) return { kind: "forbidden", code, message: "permissionDenied" }
  if (code === "invalid_invitation" && (status === 400 || status === 422)) {
    return { kind: "invalid", code, message: "invitationInvalid" }
  }
  if (code === "last_superuser" && status === 409) {
    return { kind: "conflict", code, message: "lastSuperuser" }
  }
  if (status === 404) return { kind: "invalid", code, message: "recordMissing" }
  if (status === 409) {
    if (code === "resource_ambiguous") return { kind: "conflict", code, message: "resourceAmbiguous" }
    if (code === "operation_in_progress") return { kind: "conflict", code, message: "operationInProgress" }
    if (code === "idempotency_key_conflict") return { kind: "conflict", code, message: "idempotencyConflict" }
    return { kind: "conflict", code, message: "conflict" }
  }
  if (status === 400 || status === 422) return { kind: "invalid", code, message: "invalidInput" }
  if (status === 408 || status === 502 || status === 503 || status === 504 || (status !== null && status >= 500)) {
    return phase === "mutation"
      ? { kind: "uncertain", code, message: "outcomeUncertain" }
      : { kind: "unavailable", code, message: "unavailable" }
  }
  if (data.kind === "network" || error instanceof TypeError) {
    return phase === "mutation"
      ? { kind: "uncertain", code, message: "outcomeUncertain" }
      : { kind: "unavailable", code, message: "unavailable" }
  }
  if (data.kind === "aborted" || (error instanceof DOMException && error.name === "AbortError")) {
    // A transport-side cancellation of a mutation can arrive after the server
    // accepted the write. A caller scope-switch is ignored upstream instead.
    return phase === "mutation"
      ? { kind: "uncertain", code, message: "outcomeUncertain" }
      : { kind: "unavailable", code, message: "requestCancelled" }
  }
  return { kind: "unknown", code, message: "unknownError" }
}
