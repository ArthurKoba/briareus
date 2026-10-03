import { flushPromises, mount } from "@vue/test-utils"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import AccountsPanel from "@/features/accounts/AccountsPanel.vue"
import AppDialog from "@/shared/ui/AppDialog.vue"

const api = vi.hoisted(() => ({
  accounts: vi.fn(), verifyAccount: vi.fn(), deleteAccount: vi.fn(),
}))
vi.mock("@/shared/api/management", () => ({ managementApi: api }))
vi.mock("@/shared/notifications/bus", () => ({
  notifications: { success: vi.fn(), error: vi.fn() },
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
      const button = wrapper.get('button[title="common.test"]')
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
  })
}
