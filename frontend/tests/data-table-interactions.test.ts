import { mount } from "@vue/test-utils"
import { computed, h, nextTick, type VNode } from "vue"
import { afterEach, describe, expect, it, vi } from "vitest"

import DataTable from "@/shared/ui/DataTable.vue"

vi.mock("@/shared/lib/preferences", () => ({
  uiPreferences: { density: { value: "compact" } },
}))

// DOM emulation has no layout. Exercise both DataTable templates with stable
// virtual row positions; real scroll/layout behavior requires browser acceptance.
vi.mock("@tanstack/vue-virtual", () => ({
  useVirtualizer: (options: { value: { count: number } }) => computed(() => ({
    getVirtualItems: () => Array.from({ length: options.value.count }, (_, index) => ({
      key: index, index, start: index * 32, size: 32,
    })),
    getTotalSize: () => options.value.count * 32,
  })),
}))

const mounted: ReturnType<typeof mount>[] = []
const record = { id: "row-1", name: "Selectable account name" }

function table(virtual: boolean, slot?: () => VNode, clickable = true) {
  const wrapper = mount(DataTable, {
    attachTo: document.body,
    props: {
      columns: [{ key: "name", dataIndex: "name", title: "Account" }],
      dataSource: [record],
      clickable,
      virtual,
    },
    ...(slot ? { slots: { bodyCell: slot } } : {}),
  })
  mounted.push(wrapper)
  return wrapper
}

afterEach(() => {
  for (const wrapper of mounted.splice(0)) wrapper.unmount()
  window.getSelection()?.removeAllRanges()
  document.body.innerHTML = ""
})

for (const virtual of [false, true]) {
  describe(`DataTable actions (virtual=${virtual})`, () => {
    it("opens the record when the non-interactive row content is clicked", async () => {
      const wrapper = table(virtual)
      await wrapper.get(".ts-table-row span").trigger("click")
      expect(wrapper.emitted("rowClick")).toEqual([[record]])
    })

    it("does not emit clicks for a non-clickable table", async () => {
      const wrapper = table(virtual, undefined, false)
      await wrapper.get(".ts-table-row span").trigger("click")
      expect(wrapper.emitted("rowClick")).toBeUndefined()
    })

    it.each(["button", "a"])("does not open a row for a nested SVG inside %s", async (tag) => {
      const action = vi.fn()
      const wrapper = table(virtual, () => h(tag, { onClick: action }, [
        h("svg", [h("path", { d: "M0 0h1" })]),
      ]))
      await wrapper.get(".ts-table-row path").trigger("click")
      expect(action).toHaveBeenCalledTimes(1)
      expect(wrapper.emitted("rowClick")).toBeUndefined()
    })

    it("keeps the original action boundary when the clicked SVG is detached", async () => {
      const action = vi.fn((event: MouseEvent) => {
        // Same propagation edge as replacing a verification icon with a spinner:
        // current closest() no longer sees the button, original event path still does.
        (event.target as Element).remove()
      })
      const wrapper = table(virtual, () => h("button", { onClick: action }, [
        h("svg", [h("path", { d: "M0 0h1" })]),
      ]))
      const path = wrapper.get(".ts-table-row path").element
      path.dispatchEvent(new MouseEvent("click", { bubbles: true, composed: true }))
      await nextTick()
      expect(action).toHaveBeenCalledTimes(1)
      expect(path.isConnected).toBe(false)
      expect(wrapper.emitted("rowClick")).toBeUndefined()
    })

    it("does not open the row for an explicitly marked custom action", async () => {
      const action = vi.fn()
      const wrapper = table(virtual, () => h("span", { "data-row-action": "", onClick: action }, "Action"))
      await wrapper.get("[data-row-action]").trigger("click")
      expect(action).toHaveBeenCalledTimes(1)
      expect(wrapper.emitted("rowClick")).toBeUndefined()
    })

    it("does not open the record when selecting text within the row", async () => {
      const wrapper = table(virtual)
      const text = wrapper.get(".ts-table-row span").element.firstChild!
      const range = document.createRange()
      range.setStart(text, 0)
      range.setEnd(text, 10)
      window.getSelection()?.addRange(range)
      await wrapper.get(".ts-table-row span").trigger("click")
      expect(wrapper.emitted("rowClick")).toBeUndefined()
    })

    it("ignores selections elsewhere when a normal row is clicked", async () => {
      const wrapper = table(virtual)
      const other = document.createElement("p")
      other.textContent = "Selected outside"
      document.body.append(other)
      const range = document.createRange()
      range.selectNodeContents(other)
      window.getSelection()?.addRange(range)
      await wrapper.get(".ts-table-row span").trigger("click")
      expect(wrapper.emitted("rowClick")).toEqual([[record]])
    })
  })
}
