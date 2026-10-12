import { watch } from "vue"
import { createI18n } from "vue-i18n"
import en from "./locales/en"
import ru from "./locales/ru"
import { uiPreferences } from "@/shared/lib/preferences"

export type AppLocale = "en" | "ru"
export const i18n = createI18n({ legacy: false, locale: uiPreferences.locale.value, fallbackLocale: "en", messages: { en, ru } })
// Sync the actual translation engine and document language, including
// preference changes restored in another authorized browser tab.
watch(uiPreferences.locale, locale => {
  i18n.global.locale.value = locale
  document.documentElement.lang = locale
}, { immediate: true })
export function setLocale(locale: AppLocale): void { uiPreferences.locale.value = locale }
