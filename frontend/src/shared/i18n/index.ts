import { createI18n } from "vue-i18n"
import en from "./locales/en"
import ru from "./locales/ru"
import { uiPreferences } from "@/shared/lib/preferences"

export type AppLocale = "en" | "ru"
export const i18n = createI18n({ legacy: false, locale: uiPreferences.locale.value, fallbackLocale: "en", messages: { en, ru } })
export function setLocale(locale: AppLocale): void { uiPreferences.locale.value = locale; i18n.global.locale.value = locale; document.documentElement.lang = locale }
document.documentElement.lang = uiPreferences.locale.value
