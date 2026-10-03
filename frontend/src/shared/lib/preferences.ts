import { ref, watch } from "vue"

export type ThemePreference = "dark" | "light" | "system"

const STORAGE_KEY = "mcp-management:ui"
const theme = ref<ThemePreference>("system")
const sidebarCollapsed = ref(false)

function readPreferences(): void {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return
    const parsed = JSON.parse(raw) as { theme?: ThemePreference; sidebarCollapsed?: boolean }
    if (parsed.theme === "dark" || parsed.theme === "light" || parsed.theme === "system") {
      theme.value = parsed.theme
    }
    sidebarCollapsed.value = Boolean(parsed.sidebarCollapsed)
  } catch {
    // Corrupt browser-local preferences must never prevent the console from starting.
  }
}

function persistPreferences(): void {
  localStorage.setItem(
    STORAGE_KEY,
    JSON.stringify({ theme: theme.value, sidebarCollapsed: sidebarCollapsed.value }),
  )
}

function applyTheme(): void {
  const prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches
  document.documentElement.classList.toggle(
    "dark",
    theme.value === "dark" || (theme.value === "system" && prefersDark),
  )
}

readPreferences()
watch([theme, sidebarCollapsed], persistPreferences)
watch(theme, applyTheme, { immediate: true })

export function useUiPreferences() {
  return { theme, sidebarCollapsed }
}
