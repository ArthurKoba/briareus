import { flushPromises, mount } from "@vue/test-utils"
import { afterEach, describe, expect, it, vi } from "vitest"

import RealtimeStatus from "@/shared/ui/RealtimeStatus.vue"

const bus = vi.hoisted(() => ({
  state: { status: "connected", enabled: true, lastRemoteEventAt: "2026-10-03T20:00:00Z" },
  setEnabled: vi.fn(),
}))
vi.mock("@/shared/events/bus", () => ({ eventBus: bus }))
vi.mock("vue-i18n", () => ({ useI18n: () => ({ t: (key: string) => ({
  "realtime.title": "Соединение", "realtime.tabHint": "Автоматическое обновление данных в этой вкладке.",
  "realtime.connecting": "Подключение…", "realtime.idle": "Нет соединения", "realtime.off": "Отключено",
  "realtime.enabled": "Автообновление", "realtime.enabledHint": "Только для вкладки", "realtime.turnOn": "Включить соединение",
  "realtime.turnOff": "Отключить соединение", "realtime.lastEvent": "Последнее событие", "common.connected": "Подключено",
}[key] ?? key) }) }))

const mounted: ReturnType<typeof mount>[] = []
afterEach(() => {
  for (const wrapper of mounted.splice(0)) wrapper.unmount()
  document.body.innerHTML = ""
  bus.setEnabled.mockClear()
  bus.state.status = "connected"
  bus.state.enabled = true
})

describe("connection status popover", () => {
  it("uses connection naming, hides transport noise and toggles with an accessible switch", async () => {
    const wrapper = mount(RealtimeStatus, { attachTo: document.body })
    mounted.push(wrapper)
    await wrapper.get('button[aria-label^="Соединение:"]').trigger("click")
    await flushPromises()
    expect(document.body.textContent).toContain("Соединение")
    expect(document.body.textContent).toContain("Автообновление")
    expect(document.body.textContent).not.toContain("websocket")
    expect(document.body.textContent).not.toContain("Подписки")
    const toggle = document.body.querySelector('[role="switch"]') as HTMLButtonElement
    expect(toggle).toBeTruthy()
    expect(toggle.getAttribute("aria-checked")).toBe("true")
    toggle.click()
    await flushPromises()
    expect(bus.setEnabled).toHaveBeenCalledWith(false)
  })

  it("dismisses when clicking outside", async () => {
    const wrapper = mount(RealtimeStatus, { attachTo: document.body })
    mounted.push(wrapper)
    await wrapper.get('button[aria-label^="Соединение:"]').trigger("click")
    await flushPromises()
    expect(document.body.textContent).toContain("Автоматическое обновление данных")
    document.body.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true }))
    document.body.dispatchEvent(new MouseEvent("click", { bubbles: true }))
    await flushPromises()
    expect(document.body.textContent).not.toContain("Автоматическое обновление данных")
  })
})
