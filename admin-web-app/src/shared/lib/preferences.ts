import { ref, watch } from "vue"

export type ThemePreference = "dark" | "light" | "system"
export type DensityPreference = "comfortable" | "compact"
export type LocalePreference = "en" | "ru"
/** Display preference ONLY. Never changes server TZ, audit timestamps or
 * authenticated Team/Project policies. */
export type DisplayTimeZone = "system" | "UTC"

const STORAGE_KEY = "briareus:ui:v1"
const theme = ref<ThemePreference>("system")
const sidebarCollapsed = ref(false)
const density = ref<DensityPreference>("compact")
const locale = ref<LocalePreference>("ru")
const displayTimeZone = ref<DisplayTimeZone>("system")
/** Explicit B14 local diagnostics consent. Existing B13 telemetry booleans do
 * not authorize new instrumentation or future network delivery. */
const DIAGNOSTICS_CONSENT_KEY = "briareus:diagnostics-consent:v1"
const diagnosticsConsent = ref(false)

type StoredPreferences = Partial<{
  theme: ThemePreference
  sidebarCollapsed: boolean
  density: DensityPreference
  locale: LocalePreference
  displayTimeZone: DisplayTimeZone
}>

function applyStored(p: StoredPreferences): void {
  if (["dark", "light", "system"].includes(String(p.theme))) theme.value = p.theme as ThemePreference
  if (typeof p.sidebarCollapsed === "boolean") sidebarCollapsed.value = p.sidebarCollapsed
  if (p.density === "compact" || p.density === "comfortable") density.value = p.density
  if (p.locale === "en" || p.locale === "ru") locale.value = p.locale
  if (p.displayTimeZone === "UTC" || p.displayTimeZone === "system")displayTimeZone.value = p.displayTimeZone
}

function readPreferences(): void {
  try {
    const current = localStorage.getItem(STORAGE_KEY)
    if (current) {
      applyStored(JSON.parse(current) as StoredPreferences)
      return
    }
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
    displayTimeZone: displayTimeZone.value,
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
watch([theme, sidebarCollapsed, density, locale, displayTimeZone], persist)
// Consent is independent of UI preferences and cannot be inherited from an
// older application or from pre-B14 implicit telemetry defaults.
try { diagnosticsConsent.value = localStorage.getItem(DIAGNOSTICS_CONSENT_KEY) === "granted" }
catch { diagnosticsConsent.value = false }
watch(diagnosticsConsent, allowed => {
  try { if (allowed) localStorage.setItem(DIAGNOSTICS_CONSENT_KEY, "granted")
        else localStorage.removeItem(DIAGNOSTICS_CONSENT_KEY) }
  catch { diagnosticsConsent.value = false }
}, {flush:"sync"})
watch(theme, applyTheme, { immediate: true })
watch(density, applyDensity, { immediate: true })

window.addEventListener("storage", (event) => {
  // Clearing consent in another tab must immediately stop and purge local
  // diagnostics here too; cannot inherit pre-B14 telemetry settings.
  if(event.key===DIAGNOSTICS_CONSENT_KEY){
    diagnosticsConsent.value=event.newValue==="granted"
    return
  }
  if (event.key !== STORAGE_KEY || !event.newValue) return
  try {
    applyStored(JSON.parse(event.newValue) as StoredPreferences)
  } catch {
    // Ignore corrupt cross-tab preference events.
  }
})

export const uiPreferences = { theme, sidebarCollapsed, density, locale, displayTimeZone, diagnosticsConsent }
export function useUiPreferences() { return uiPreferences }
