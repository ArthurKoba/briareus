import { describe, expect, it } from "vitest"

import type { AccountPayload } from "@/shared/api/management"
import { accountConnectionChanged, accountDraftDirty, normalizeAccountDraft } from "@/features/accounts/model/account-draft"

const variants: Array<[string, AccountPayload]> = [
  ["github token", { alias: "gh-token", provider: "github", auth_type: "github_token", base_url: "https://api.github.com", external_id: "", verify_tls: true, ca_cert_pem: "", enabled: true, credential: "" }],
  ["github app", { alias: "gh-app", provider: "github", auth_type: "github_app", base_url: "https://api.github.com", external_id: "12345", verify_tls: true, ca_cert_pem: "", enabled: true, credential: "" }],
  ["gitlab", { alias: "gitlab", provider: "gitlab", auth_type: "private_token", base_url: "https://gitlab.example.test", external_id: "", verify_tls: true, ca_cert_pem: "", enabled: true, credential: "" }],
  ["signoz", { alias: "signoz", provider: "signoz", auth_type: "signoz_api_key", base_url: "https://signoz.example.test", external_id: "", verify_tls: true, ca_cert_pem: "CERT", enabled: true, credential: "" }],
  ["coolify", { alias: "coolify", provider: "coolify", auth_type: "coolify_api_token", base_url: "https://coolify.example.test", external_id: "", verify_tls: false, ca_cert_pem: "CERT", enabled: true, credential: "" }],
]

describe.each(variants)("account dirty model: %s", (_name, baseline) => {
  it("starts clean and ignores blank secret plus harmless URL/whitespace normalization", () => {
    expect(accountDraftDirty({ ...baseline, alias: ` ${baseline.alias.toUpperCase()} `, base_url: `${baseline.base_url}/`, credential: "   " }, baseline)).toBe(false)
  })

  it("treats alias/enabled as dirty metadata without requiring connection verification", () => {
    for (const current of [{ ...baseline, alias: `${baseline.alias}-renamed` }, { ...baseline, enabled: !baseline.enabled }]) {
      expect(accountDraftDirty(current, baseline)).toBe(true)
      expect(accountConnectionChanged(current, baseline)).toBe(false)
    }
  })

  it("requires connection verification for connection-affecting fields and returns clean when reverted", () => {
    const candidates: AccountPayload[] = [
      { ...baseline, auth_type: `${baseline.auth_type}-changed` },
      { ...baseline, base_url: "https://changed.example.test" },
      { ...baseline, external_id: `${baseline.external_id ?? ""}changed` },
      { ...baseline, verify_tls: !baseline.verify_tls },
      { ...baseline, ca_cert_pem: `${baseline.ca_cert_pem ?? ""} changed` },
      { ...baseline, credential: "new-secret" },
    ]
    for (const current of candidates) {
      expect(accountDraftDirty(current, baseline)).toBe(true)
      expect(accountConnectionChanged(current, baseline)).toBe(true)
    }
    expect(accountDraftDirty({ ...baseline }, baseline)).toBe(false)
    expect(accountConnectionChanged({ ...baseline }, baseline)).toBe(false)
  })
})

it("normalizes provider URL trailing slash and CA/ID whitespace", () => {
  const [, payload] = variants[2]
  expect(normalizeAccountDraft({ ...payload, base_url: `${payload.base_url}/`, external_id: "  id  ", ca_cert_pem: " CERT \n" })).toMatchObject({
    base_url: payload.base_url,
    external_id: "id",
    ca_cert_pem: "CERT",
  })
})
