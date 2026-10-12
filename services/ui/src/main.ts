import { createApp } from "vue"
import App from "@/app/App.vue"
import "@/app/styles.css"
import { i18n } from "@/shared/i18n"
import { notifications } from "@/shared/notifications/bus"
import { browserTelemetry } from "@/features/platform/model/browser-telemetry"

const app=createApp(App)
app.use(i18n)
window.addEventListener("error",()=>{
  browserTelemetry.error("app","window")
  notifications.error(String(i18n.global.t("notifications.frontendError")),String(i18n.global.t("notifications.technicalError")))
})
window.addEventListener("unhandledrejection",event=>{
  // Only the exception CATEGORY is observed; never stack/message/cause.
  if (event.reason instanceof DOMException && event.reason.name === "AbortError") return
  browserTelemetry.error("app","promise")
  notifications.error(String(i18n.global.t("notifications.frontendError")),String(i18n.global.t("notifications.technicalError")))
})
app.mount("#app")
// NavigationTiming is read only as coarse duration; NEVER resource URL/name.
window.addEventListener("load",()=>{
  const entry=performance.getEntriesByType("navigation")[0]
  if(entry && Number.isFinite(entry.duration))browserTelemetry.performance(entry.duration)
},{once:true})
