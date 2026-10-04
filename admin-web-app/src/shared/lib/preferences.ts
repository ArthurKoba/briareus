import { ref, watch } from "vue"

export type ThemePreference = "dark" | "light" | "system"
export type DensityPreference = "comfortable" | "compact"
export type LocalePreference = "en" | "ru"

const STORAGE_KEY = "mcp-bridge:ui:v2"
const LEGACY_STORAGE_KEY = "mcp-admin:ui"
const theme = ref<ThemePreference>("system")
const sidebarCollapsed = ref(false)
const density = ref<DensityPreference>("compact")
const locale = ref<LocalePreference>("ru")
const telemetryEnabled = ref(true)

type StoredPreferences = Partial<{
  theme: ThemePreference
  sidebarCollapsed: boolean
  density: DensityPreference
  locale: LocalePreference
  telemetryEnabled: boolean
}>

function applyStored(p: StoredPreferences, legacy = false): void {
  if (["dark", "light", "system"].includes(String(p.theme))) theme.value = p.theme as ThemePreference
  if (typeof p.sidebarCollapsed === "boolean") sidebarCollapsed.value = p.sidebarCollapsed
  if (!legacy && (p.density === "compact" || p.density === "comfortable")) density.value = p.density
  if (p.locale === "en" || p.locale === "ru") locale.value = p.locale
  if (typeof p.telemetryEnabled === "boolean") telemetryEnabled.value = p.telemetryEnabled
}

function readPreferences(): void {
  try {
    const current = localStorage.getItem(STORAGE_KEY)
    if (current) {
      applyStored(JSON.parse(current) as StoredPreferences)
      return
    }
    const legacy = localStorage.getItem(LEGACY_STORAGE_KEY)
    if (legacy) applyStored(JSON.parse(legacy) as StoredPreferences, true)
  } catch {
    // Ignore corrupt browser-local preferences.
  }
}

function persist(): void {
  localStorage.setItem(STORAGE_KEY, JSON.stringify({
    theme: theme.value,
    sidebarCollapsed: sidebarCollapsed.value,
    density: density.value,
    locale: locale.value,
    telemetryEnabled: telemetryEnabled.value,
  }))
}

function applyTheme(): void {
  const dark = window.matchMedia("(prefers-color-scheme: dark)").matches
  document.documentElement.classList.toggle("dark", theme.value === "dark" || (theme.value === "system" && dark))
}

function applyDensity(): void {
  document.documentElement.dataset.density = density.value
}

readPreferences()
watch([theme, sidebarCollapsed, density, locale, telemetryEnabled], persist)
watch(theme, applyTheme, { immediate: true })
watch(density, applyDensity, { immediate: true })

window.addEventListener("storage", (event) => {
  if (event.key !== STORAGE_KEY || !event.newValue) return
  try {
    applyStored(JSON.parse(event.newValue) as StoredPreferences)
  } catch {
    // Ignore corrupt cross-tab preference events.
  }
})

export const uiPreferences = { theme, sidebarCollapsed, density, locale, telemetryEnabled }
export function useUiPreferences() { return uiPreferences }
