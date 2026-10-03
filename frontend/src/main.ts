import { createApp } from "vue"
import App from "@/app/App.vue"
import "@/app/styles.css"
import { i18n } from "@/shared/i18n"
import { frontendTelemetry } from "@/shared/telemetry/client"
import { notifications } from "@/shared/notifications/bus"

const app=createApp(App)
app.use(i18n)
window.addEventListener("error",event=>{frontendTelemetry.error("window.error",event.error??event.message);notifications.error("Frontend error",event.message)})
window.addEventListener("unhandledrejection",event=>{frontendTelemetry.error("window.unhandledrejection",event.reason);notifications.error("Unhandled frontend error",event.reason instanceof Error?event.reason.message:String(event.reason))})
frontendTelemetry.event("app.start",{language:navigator.language,user_agent_family:navigator.userAgent.includes("Chrome")?"chromium":"other"})
app.mount("#app")
