/** Existing global Admin v1 account API. Never use in a Project-scope context. */
import { request, jsonBody, type RequestOptions } from "@/shared/api/legacy-client"
import type { AccountRecord, AccountPayload, AccountCandidatePayload, AccountCandidateResult } from "@/features/accounts/model/legacy-api-types"

export const legacyAccountApi = {
  accounts: (options: RequestOptions = {}): Promise<{ accounts: AccountRecord[]; count: number }> => request("/accounts", {}, options),
  createAccount: (payload: AccountPayload): Promise<AccountRecord> => request("/accounts", { method: "POST", body: jsonBody(payload) }),
  updateAccount: (record: AccountRecord, payload: AccountPayload): Promise<AccountRecord> => request(`/accounts/${record.provider}/${record.id}`, { method: "PUT", body: jsonBody({ ...payload, expected_updated_at: record.updated_at }) }),
  deleteAccount: (record: AccountRecord): Promise<unknown> => request(`/accounts/${record.provider}/${record.id}`, { method: "DELETE" }),
  verifyAccount: (record: AccountRecord): Promise<Record<string, unknown>> => request(`/accounts/${record.provider}/${record.id}/verify`, { method: "POST", body: "{}" }, { notifyErrors: false }),
  verifyAccountCandidate: (payload: AccountCandidatePayload): Promise<AccountCandidateResult> => request("/accounts/verify-candidate", { method: "POST", body: jsonBody(payload) }, { notifyErrors: false }),
}
