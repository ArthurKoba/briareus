import { createApp } from "vue"
import App from "@/app/App.vue"
import "@/app/styles.css"
import { i18n } from "@/shared/i18n"
import { frontendTelemetry } from "@/shared/telemetry/client"
import { notifications } from "@/shared/notifications/bus"

const app=createApp(App)
app.use(i18n)
window.addEventListener("error",event=>{
  frontendTelemetry.error("window.error",event.error??event.message)
  notifications.error(String(i18n.global.t("notifications.frontendError")),String(i18n.global.t("notifications.technicalError")))
})
window.addEventListener("unhandledrejection",event=>{
  if (event.reason instanceof DOMException && event.reason.name === "AbortError") return
  frontendTelemetry.error("window.unhandledrejection",event.reason)
  notifications.error(String(i18n.global.t("notifications.frontendError")),String(i18n.global.t("notifications.technicalError")))
})
frontendTelemetry.event("app.start",{language:navigator.language,user_agent_family:navigator.userAgent.includes("Chrome")?"chromium":"other"})
app.mount("#app")
