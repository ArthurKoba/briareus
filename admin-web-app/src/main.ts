import { createApp } from "vue"
import App from "@/app/App.vue"
import "@/app/styles.css"
import { i18n } from "@/shared/i18n"
import { notifications } from "@/shared/notifications/bus"

const app=createApp(App)
app.use(i18n)
window.addEventListener("error",event=>{
  notifications.error(String(i18n.global.t("notifications.frontendError")),String(i18n.global.t("notifications.technicalError")))
})
window.addEventListener("unhandledrejection",event=>{
  if (event.reason instanceof DOMException && event.reason.name === "AbortError") return
  notifications.error(String(i18n.global.t("notifications.frontendError")),String(i18n.global.t("notifications.technicalError")))
})
app.mount("#app")
