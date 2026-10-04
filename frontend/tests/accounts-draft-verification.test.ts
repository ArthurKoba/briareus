import { flushPromises, mount } from "@vue/test-utils"
import { nextTick } from "vue"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import AccountsPanel from "@/features/accounts/AccountsPanel.vue"

const notify = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn() }))
const api = vi.hoisted(() => ({
  accounts: vi.fn(),
  verifyAccount: vi.fn(),
  verifyAccountCandidate: vi.fn(),
  createAccount: vi.fn(),
  updateAccount: vi.fn(),
  deleteAccount: vi.fn(),
}))
vi.mock("@/shared/api/management", () => ({ managementApi: api }))
vi.mock("@/shared/notifications/bus", () => ({ notifications: notify }))
vi.mock("vue-i18n", () => ({ useI18n: () => ({ t: (key: string) => key }) }))
vi.mock("@/shared/lib/preferences", () => ({ uiPreferences: { density: { value: "compact" } } }))
vi.mock("ant-design-vue", () => ({
  Select: { template: "<div />" },
  Switch: { template: '<button type="button" role="switch" />' },
}))

const mounted: ReturnType<typeof mount>[] = []
const record = {
  id: "account-1", provider: "gitlab" as const, alias: "existing", auth_type: "private_token",
  base_url: "https://gitlab.old.test", verify_tls: true, enabled: true,
  external_id: "", ca_cert_pem: "", created_at: "2026-10-03T00:00:00Z",
  updated_at: "2026-10-03T00:00:00Z",
}

beforeEach(() => {
  api.accounts.mockResolvedValue({ accounts: [] })
  api.verifyAccount.mockResolvedValue({ ok: true })
  api.verifyAccountCandidate.mockImplementation(async (payload: any) => ({ ok: true, provider: payload.provider, draft_revision: payload.draft_revision }))
  api.createAccount.mockResolvedValue({ ...record, id: "created-1", alias: "new-account" })
  api.updateAccount.mockResolvedValue(record)
  api.deleteAccount.mockResolvedValue({ deleted: true })
  notify.success.mockReset()
  notify.error.mockReset()
})

afterEach(() => {
  for (const wrapper of mounted.splice(0)) wrapper.unmount()
  document.body.innerHTML = ""
})

async function panel(accounts: unknown[] = [], provider: "github" | "gitlab" = "github") {
  api.accounts.mockResolvedValue({ accounts })
  const wrapper = mount(AccountsPanel, {
    attachTo: document.body,
    props: { title: provider, description: "", providers: [provider], defaultProvider: provider },
  })
  mounted.push(wrapper)
  await flushPromises()
  return wrapper
}

function dialogElement(): HTMLElement {
  return document.body.querySelector<HTMLElement>('[role="dialog"]')!
}

function modalButton(text: string): HTMLButtonElement {
  return [...dialogElement().querySelectorAll<HTMLButtonElement>("button")].find(button => button.textContent?.includes(text))!
}

function modalInput(selector: string): HTMLInputElement {
  return dialogElement().querySelector<HTMLInputElement>(selector)!
}

async function setInput(input: HTMLInputElement, value: string): Promise<void> {
  input.value = value
  input.dispatchEvent(new Event("input", { bubbles: true }))
  await nextTick()
}

describe("account draft verification", () => {
  it("requires candidate verification before creating and never uses persisted verify", async () => {
    const wrapper = await panel([], "github")
    await wrapper.findAll("button").find(button => button.text().includes("accounts.add"))!.trigger("click")
    await setInput(modalInput('input.field:not([type="password"])'), "new-account")
    await setInput(modalInput('input[type="password"]'), "new-secret")
    const add = modalButton("common.add")
    expect(add.disabled).toBe(true)

    modalButton("common.test").click()
    await flushPromises()
    expect(api.verifyAccountCandidate).toHaveBeenCalledTimes(1)
    const candidate = api.verifyAccountCandidate.mock.calls[0][0]
    expect(candidate).toMatchObject({ alias: "new-account", provider: "github", credential: "new-secret" })
    expect(candidate.account_id).toBeUndefined()
    expect(candidate.draft_revision).toMatch(/^1:/)
    expect(api.createAccount).not.toHaveBeenCalled()
    expect(api.verifyAccount).not.toHaveBeenCalled()
    expect(add.disabled).toBe(false)

    add.click()
    await flushPromises()
    expect(api.createAccount).toHaveBeenCalledTimes(1)
    expect(api.verifyAccount).not.toHaveBeenCalled()
  })

  it("invalidates a successful check as soon as a connection field changes", async () => {
    const wrapper = await panel([], "github")
    await wrapper.findAll("button").find(button => button.text().includes("accounts.add"))!.trigger("click")
    await setInput(modalInput('input.field:not([type="password"])'), "new-account")
    const secret = modalInput('input[type="password"]')
    await setInput(secret, "secret-one")
    modalButton("common.test").click()
    await flushPromises()
    expect(modalButton("common.add").disabled).toBe(false)

    await setInput(secret, "secret-two")
    expect(modalButton("common.add").disabled).toBe(true)
    expect(dialogElement().textContent).toContain("accounts.verifyDraftRequired")
  })

  it("ignores an out-of-order success for a draft that changed while verification was running", async () => {
    let finish!: (value: unknown) => void
    api.verifyAccountCandidate.mockImplementationOnce((payload: any) => new Promise(resolve => {
      finish = () => resolve({ ok: true, provider: payload.provider, draft_revision: payload.draft_revision })
    }))
    const wrapper = await panel([], "github")
    await wrapper.findAll("button").find(button => button.text().includes("accounts.add"))!.trigger("click")
    await setInput(modalInput('input.field:not([type="password"])'), "new-account")
    const secret = modalInput('input[type="password"]')
    await setInput(secret, "secret-one")
    modalButton("common.test").click()
    await flushPromises()
    await setInput(secret, "secret-two")
    expect(modalButton("common.test").disabled).toBe(true)
    modalButton("common.test").click()
    expect(api.verifyAccountCandidate).toHaveBeenCalledTimes(1)
    finish({})
    await flushPromises()
    expect(modalButton("common.add").disabled).toBe(true)
    expect(dialogElement().textContent).not.toContain("accounts.draftVerified")
  })

  it("allows metadata-only edit without re-verification", async () => {
    const wrapper = await panel([record], "gitlab")
    await wrapper.get(".ts-table-row .font-medium").trigger("click")
    await setInput(modalInput('input.field:not([type="password"])'), "renamed")
    const save = modalButton("common.confirm")
    expect(save.disabled).toBe(false)
    save.click()
    await flushPromises()
    expect(api.verifyAccountCandidate).not.toHaveBeenCalled()
    expect(api.updateAccount).toHaveBeenCalledTimes(1)
  })

  it("requires candidate verification for a changed edit and reuses the stored credential", async () => {
    const wrapper = await panel([record], "gitlab")
    await wrapper.get(".ts-table-row .font-medium").trigger("click")
    const baseUrl = modalInput('input[placeholder="https://…"]')
    await setInput(baseUrl, "https://gitlab.new.test")
    const save = modalButton("common.confirm")
    expect(save.disabled).toBe(true)
    modalButton("common.test").click()
    await flushPromises()
    expect(api.verifyAccountCandidate).toHaveBeenCalledTimes(1)
    expect(api.verifyAccountCandidate.mock.calls[0][0]).toMatchObject({
      account_id: "account-1",
      base_url: "https://gitlab.new.test",
      credential: "",
    })
    expect(save.disabled).toBe(false)
  })
})
