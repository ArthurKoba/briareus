import { flushPromises, mount } from "@vue/test-utils"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import AccountsPanel from "@/features/accounts/AccountsPanel.vue"
import AppDialog from "@/shared/ui/AppDialog.vue"

const notify = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn() }))
const api = vi.hoisted(() => ({
  accounts: vi.fn(), verifyAccount: vi.fn(), verifyAccountCandidate: vi.fn(), createAccount: vi.fn(), updateAccount: vi.fn(), deleteAccount: vi.fn(),
}))
vi.mock("@/shared/api/management", () => ({ managementApi: api }))
vi.mock("@/shared/notifications/bus", () => ({
  notifications: notify,
}))
vi.mock("vue-i18n", () => ({ useI18n: () => ({ t: (key: string) => key }) }))
vi.mock("@/shared/lib/preferences", () => ({
  uiPreferences: { density: { value: "compact" } },
}))
vi.mock("ant-design-vue", () => ({
  Select: { template: "<div />" },
  Switch: { template: '<button type="button" role="switch" />' },
}))

const mounted: ReturnType<typeof mount>[] = []

beforeEach(() => {
  Object.defineProperty(window, "confirm", { configurable: true, writable: true, value: vi.fn(() => false) })
  api.verifyAccount.mockResolvedValue({ status: "ok" })
  api.deleteAccount.mockResolvedValue({ deleted: true })
})
afterEach(() => {
  for (const wrapper of mounted.splice(0)) wrapper.unmount()
  document.body.innerHTML = ""
})

for (const provider of ["github", "gitlab", "signoz", "coolify"] as const) {
  describe(`account row actions: ${provider}`, () => {
    async function panel() {
      const record = {
        id: "test-id", provider, alias: `${provider}-fixture`, auth_type: "private_token",
        base_url: "https://provider.invalid", verify_tls: true, enabled: true,
        external_id: "", ca_cert_pem: "", created_at: "2026-10-03T00:00:00Z",
        updated_at: "2026-10-03T00:00:00Z",
      }
      api.accounts.mockResolvedValue({ accounts: [record] })
      const wrapper = mount(AccountsPanel, {
        attachTo: document.body,
        props: { title: provider, description: "", providers: [provider], defaultProvider: provider },
      })
      mounted.push(wrapper)
      await flushPromises()
      return { wrapper, record }
    }

    it.each(["button", "svg", "path"])("verification via %s never opens the account dialog", async (target) => {
      const { wrapper, record } = await panel()
      const button = wrapper.get('.ts-table-row [data-row-action] button')
      await (target === "button" ? button : button.get(target)).trigger("click")
      await flushPromises()
      expect(api.verifyAccount).toHaveBeenCalledExactlyOnceWith(record)
      expect(wrapper.getComponent(AppDialog).props("open")).toBe(false)
    })

    it("opens the dialog on the ordinary row content", async () => {
      const { wrapper } = await panel()
      await wrapper.get(".ts-table-row .font-medium").trigger("click")
      expect(wrapper.getComponent(AppDialog).props("open")).toBe(true)
      expect(api.verifyAccount).not.toHaveBeenCalled()
    })

    it("only asks for deletion when the delete SVG is clicked", async () => {
      const confirm = vi.spyOn(window, "confirm").mockReturnValue(false)
      const { wrapper } = await panel()
      await wrapper.get('button[title="common.delete"] svg').trigger("click")
      expect(confirm).toHaveBeenCalledTimes(1)
      expect(api.deleteAccount).not.toHaveBeenCalled()
      expect(wrapper.getComponent(AppDialog).props("open")).toBe(false)
    })

    it("does not open the dialog when the endpoint link is followed", async () => {
      const { wrapper } = await panel()
      const link = wrapper.get(".ts-table-row a")
      // Prevent navigation in the test only; application must preserve normal links.
      link.element.addEventListener("click", (event) => event.preventDefault(), { once: true })
      await link.get("svg").trigger("click")
      expect(wrapper.getComponent(AppDialog).props("open")).toBe(false)
      expect(api.verifyAccount).not.toHaveBeenCalled()
    })

    it("keeps successful verification inline without a duplicate success notification", async () => {
      const { wrapper } = await panel()
      await wrapper.get('.ts-table-row [data-row-action] button').trigger("click")
      await flushPromises()
      expect(notify.success).not.toHaveBeenCalled()
      expect(wrapper.get('.ts-table-row [data-row-action] button').attributes("title")).toContain("accounts.connectionVerified")
    })

    it("coalesces repeated clicks while a verification is in flight", async () => {
      let finish!: (value: unknown) => void
      api.verifyAccount.mockImplementation(() => new Promise(resolve => { finish = resolve }))
      const { wrapper } = await panel()
      const button = wrapper.get('.ts-table-row [data-row-action] button')
      ;(button.element as HTMLButtonElement).click()
      ;(button.element as HTMLButtonElement).click()
      await flushPromises()
      expect(api.verifyAccount).toHaveBeenCalledTimes(1)
      expect(button.attributes("disabled")).toBeDefined()
      expect(button.attributes("aria-busy")).toBe("true")
      expect(wrapper.getComponent(AppDialog).props("open")).toBe(false)
      finish({ ok: true })
      await flushPromises()
      expect(button.attributes("disabled")).toBeUndefined()
    })

    it("shows a failed verification next to the action without another notification", async () => {
      const { wrapper } = await panel()
      api.verifyAccount.mockRejectedValueOnce(new Error("Provider unavailable"))
      await wrapper.get('.ts-table-row [data-row-action] button').trigger("click")
      await flushPromises()
      expect(notify.error).not.toHaveBeenCalled()
      expect(wrapper.get('.ts-table-row [data-row-action] button').attributes("title")).toContain("Provider unavailable")
      expect(wrapper.getComponent(AppDialog).props("open")).toBe(false)
    })

    it("does not reuse a successful verification for a newer persisted revision", async () => {
      const { wrapper, record } = await panel()
      await wrapper.get('.ts-table-row [data-row-action] button').trigger("click")
      await flushPromises()
      expect(wrapper.get('.ts-table-row [data-row-action] button').attributes("title")).toContain("accounts.connectionVerified")
      api.accounts.mockResolvedValue({ accounts: [{ ...record, updated_at: "2026-10-03T01:00:00Z" }] })
      await wrapper.findAll("button").find(button => button.text().includes("common.refresh"))!.trigger("click")
      await flushPromises()
      expect(wrapper.get('.ts-table-row [data-row-action] button').attributes("title")).toBe("accounts.testConnection")
    })
  })
}
