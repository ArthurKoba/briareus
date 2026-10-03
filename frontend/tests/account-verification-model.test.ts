import { describe, expect, it, vi } from "vitest"

import type { AccountRecord } from "@/shared/api/management"
import { useAccountVerification } from "@/features/accounts/model/use-account-verification"

const record: AccountRecord = {
  id: "same-id", provider: "github", alias: "fixture", auth_type: "github_token",
  base_url: "https://provider.invalid", external_id: null, verify_tls: true,
  ca_cert_pem: null, enabled: true, created_at: "2026-10-03T00:00:00Z", updated_at: "revision-1",
}

describe("persisted account verification", () => {
  it("does not share state between providers with identical IDs", async () => {
    const check = vi.fn().mockResolvedValue({ ok: true })
    const model = useAccountVerification(check)
    await model.verify(record)
    expect(model.stateFor(record).status).toBe("success")
    expect(model.stateFor({ ...record, provider: "gitlab" }).status).toBe("idle")
    await model.verify({ ...record, provider: "gitlab" })
    expect(check).toHaveBeenCalledTimes(2)
  })

  it("coalesces requests and refuses to certify a changed revision with an older response", async () => {
    let finish!: () => void
    const check = vi.fn(() => new Promise<void>(resolve => { finish = resolve }))
    const model = useAccountVerification(check)
    const first = model.verify(record)
    const duplicate = model.verify(record)
    const changed = { ...record, updated_at: "revision-2" }
    const newer = model.verify(changed)
    await Promise.resolve()
    expect(check).toHaveBeenCalledTimes(1)
    expect(model.stateFor(changed).status).toBe("loading")
    finish()
    expect(await first).toBe(true)
    expect(await duplicate).toBe(true)
    expect(await newer).toBe(false)
    expect(model.stateFor(changed).status).toBe("idle")
    expect(model.stateFor(record).status).toBe("success")
  })

  it("releases its single-flight entry after synchronous failure and can retry", async () => {
    const check = vi.fn().mockImplementationOnce(() => { throw new Error("Rejected") }).mockResolvedValue({ ok: true })
    const model = useAccountVerification(check)
    expect(await model.verify(record)).toBe(false)
    expect(model.stateFor(record)).toMatchObject({ status: "error", message: "Rejected" })
    expect(await model.verify(record)).toBe(true)
    expect(check).toHaveBeenCalledTimes(2)
    expect(model.stateFor(record).status).toBe("success")
  })
})
