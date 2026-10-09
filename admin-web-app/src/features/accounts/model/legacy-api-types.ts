/** Existing Admin v1 global account DTOs; NOT Project-scoped accounts. */
export interface AccountRecord {
  id: string; alias: string; provider: "github" | "gitlab" | "signoz" | "coolify"; auth_type: string
  base_url: string; external_id: string | null; verify_tls: boolean; ca_cert_pem: string | null
  enabled: boolean; created_at: string; updated_at: string
}
export interface AccountPayload {
  alias: string; provider: AccountRecord["provider"]; auth_type: string; base_url?: string; external_id?: string
  verify_tls?: boolean; ca_cert_pem?: string; enabled?: boolean; credential?: string
}
export interface AccountCandidatePayload extends AccountPayload { account_id?: string; draft_revision: string }
export interface AccountCandidateResult { ok: true; provider: AccountRecord["provider"]; draft_revision: string }
