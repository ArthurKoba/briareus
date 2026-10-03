import { afterEach, describe, expect, it, vi } from "vitest"

const originalVisibility = Object.getOwnPropertyDescriptor(document, "visibilityState")

afterEach(() => {
  vi.restoreAllMocks()
  if (originalVisibility) Object.defineProperty(document, "visibilityState", originalVisibility)
})

describe("page activity", () => {
  it("tracks focus, visibility and freeze/resume as one active state", async () => {
    let visible: DocumentVisibilityState = "visible"
    let focused = true
    Object.defineProperty(document, "visibilityState", { configurable: true, get: () => visible })
    vi.spyOn(document, "hasFocus").mockImplementation(() => focused)
    vi.resetModules()
    const { pageActivity } = await import("@/shared/lib/page-activity")
    expect(pageActivity.state.active).toBe(true)

    focused = false
    window.dispatchEvent(new Event("blur"))
    expect(pageActivity.state.active).toBe(false)

    focused = true
    window.dispatchEvent(new Event("focus"))
    expect(pageActivity.state.active).toBe(true)

    visible = "hidden"
    document.dispatchEvent(new Event("visibilitychange"))
    expect(pageActivity.state.active).toBe(false)

    visible = "visible"
    document.dispatchEvent(new Event("visibilitychange"))
    expect(pageActivity.state.active).toBe(true)

    document.dispatchEvent(new Event("freeze"))
    expect(pageActivity.state.active).toBe(false)
    document.dispatchEvent(new Event("resume"))
    expect(pageActivity.state.active).toBe(true)
  })
})
