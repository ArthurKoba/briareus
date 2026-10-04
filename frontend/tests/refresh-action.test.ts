import { mount } from "@vue/test-utils"
import { describe, expect, it, vi } from "vitest"

import RefreshAction from "@/shared/ui/RefreshAction.vue"

vi.mock("vue-i18n", () => ({ useI18n: () => ({ t: (key: string) => key }) }))

describe("RefreshAction", () => {
  it("is hidden for a synced domain and appears in manual mode", async () => {
    const wrapper = mount(RefreshAction, { props: { synced: true } })
    expect(wrapper.find("button").exists()).toBe(false)
    await wrapper.setProps({ synced: false })
    expect(wrapper.get("button").text()).toContain("common.refresh")
    await wrapper.get("button").trigger("click")
    expect(wrapper.emitted("refresh")).toHaveLength(1)
  })
})
