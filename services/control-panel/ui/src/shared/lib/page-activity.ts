import { reactive, readonly } from "vue"

type ActivityListener = (active: boolean) => void

const listeners = new Set<ActivityListener>()
let frozen = false
const initialVisible = typeof document === "undefined" || document.visibilityState === "visible"
const initialFocused = typeof document === "undefined" || document.hasFocus()
const state = reactive({
  visible: initialVisible,
  focused: initialFocused,
  frozen: false,
  active: initialVisible && initialFocused,
})

function sync(): void {
  const visible = document.visibilityState === "visible"
  const focused = document.hasFocus()
  const active = visible && focused && !frozen
  const changed = state.active !== active
  state.visible = visible
  state.focused = focused
  state.frozen = frozen
  state.active = active
  if (changed) for (const listener of listeners) listener(active)
}

function freeze(): void { frozen = true; sync() }
function resume(): void { frozen = false; sync() }

if (typeof window !== "undefined" && typeof document !== "undefined") {
  document.addEventListener("visibilitychange", sync)
  document.addEventListener("freeze", freeze)
  document.addEventListener("resume", resume)
  window.addEventListener("focus", sync)
  window.addEventListener("blur", sync)
  window.addEventListener("pageshow", resume)
}

export const pageActivity = {
  state: readonly(state),
  isActive: (): boolean => state.active,
  subscribe(listener: ActivityListener): () => void {
    listeners.add(listener)
    return () => listeners.delete(listener)
  },
}
