import type { AccountPayload } from "@/shared/api/management"

export interface NormalizedAccountDraft {
  alias: string
  provider: AccountPayload["provider"]
  auth_type: string
  base_url: string
  external_id: string
  verify_tls: boolean
  ca_cert_pem: string
  enabled: boolean
  credential_changed: boolean
}

export function normalizeAccountDraft(payload: AccountPayload): NormalizedAccountDraft {
  return {
    alias: payload.alias.trim().toLowerCase(),
    provider: payload.provider,
    auth_type: payload.auth_type,
    base_url: (payload.base_url ?? "").trim().replace(/\/+$/, ""),
    external_id: (payload.external_id ?? "").trim(),
    verify_tls: Boolean(payload.verify_tls),
    ca_cert_pem: (payload.ca_cert_pem ?? "").trim(),
    enabled: Boolean(payload.enabled),
    credential_changed: Boolean(payload.credential?.trim()),
  }
}

export function accountDraftDirty(current: AccountPayload, baseline: AccountPayload): boolean {
  return JSON.stringify(normalizeAccountDraft(current)) !== JSON.stringify(normalizeAccountDraft(baseline))
}

export function accountConnectionChanged(current: AccountPayload, baseline: AccountPayload): boolean {
  const next = normalizeAccountDraft(current)
  const previous = normalizeAccountDraft(baseline)
  return next.credential_changed
    || next.provider !== previous.provider
    || next.auth_type !== previous.auth_type
    || next.base_url !== previous.base_url
    || next.external_id !== previous.external_id
    || next.verify_tls !== previous.verify_tls
    || next.ca_cert_pem !== previous.ca_cert_pem
}
