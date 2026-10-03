<script setup lang="ts">
import { computed, defineAsyncComponent, onBeforeUnmount, onMounted, ref } from "vue"
import { Activity, AppWindow, Blocks, Bot, ChartNoAxesCombined, Database, FileText, GitBranch, Moon, PanelLeftClose, PanelLeftOpen, Settings, Sun, TerminalSquare } from "lucide-vue-next"
import { useI18n } from "vue-i18n"
import { managementApi, type ManagementBootstrap, type SessionState } from "@/shared/api/management"
import { useUiPreferences } from "@/shared/lib/preferences"
import { frontendTelemetry } from "@/shared/telemetry/client"
import { eventBus, type BusEvent } from "@/shared/events/bus"
import { notifications, type NotificationLevel } from "@/shared/notifications/bus"
import Button from "@/shared/ui/Button.vue"
import RealtimeStatus from "@/shared/ui/RealtimeStatus.vue"
import ToastHost from "@/shared/notifications/ToastHost.vue"

const DashboardPage=defineAsyncComponent(()=>import("@/pages/dashboard/DashboardPage.vue"))
const GitPage=defineAsyncComponent(()=>import("@/pages/git/GitPage.vue"))
const ObservabilityPage=defineAsyncComponent(()=>import("@/pages/observability/ObservabilityPage.vue"))
const CallsPage=defineAsyncComponent(()=>import("@/pages/calls/CallsPage.vue"))
const FilesPage=defineAsyncComponent(()=>import("@/pages/files/FilesPage.vue"))
const TerminalPage=defineAsyncComponent(()=>import("@/pages/terminal/TerminalPage.vue"))
const BrowserPage=defineAsyncComponent(()=>import("@/pages/browser/BrowserPage.vue"))
const AnalysisPage=defineAsyncComponent(()=>import("@/pages/analysis/AnalysisPage.vue"))
const OAuthPage=defineAsyncComponent(()=>import("@/pages/oauth/OAuthPage.vue"))
const SettingsPage=defineAsyncComponent(()=>import("@/pages/settings/SettingsPage.vue"))

const {t}=useI18n()
const session=ref<SessionState|null>(null),bootstrap=ref<ManagementBootstrap|null>(null),loading=ref(true),error=ref(""),username=ref(""),password=ref("")
const activePage=ref("dashboard")
let unsubscribeNotifications:undefined|(()=>void)
const {theme,sidebarCollapsed}=useUiPreferences()
const nav=computed(()=>[
  {id:"dashboard",label:t("nav.dashboard"),icon:Activity,component:DashboardPage},
  {id:"git",label:t("nav.git"),icon:GitBranch,component:GitPage},
  {id:"observability",label:t("nav.observability"),icon:ChartNoAxesCombined,component:ObservabilityPage},
  {id:"calls",label:t("nav.calls"),icon:Blocks,component:CallsPage},
  {id:"files",label:t("nav.files"),icon:FileText,component:FilesPage},
  {id:"terminal",label:t("nav.terminal"),icon:TerminalSquare,component:TerminalPage},
  {id:"browser",label:t("nav.browser"),icon:AppWindow,component:BrowserPage},
  {id:"analysis",label:t("nav.analysis"),icon:Database,component:AnalysisPage},
  {id:"oauth",label:t("nav.oauth"),icon:Bot,component:OAuthPage},
  {id:"settings",label:t("nav.settings"),icon:Settings,component:SettingsPage},
])
const current=computed(()=>nav.value.find(item=>item.id===activePage.value)??nav.value[0])
function select(id:string){
  activePage.value=id
  const target=id==="git"?"git/github":id==="observability"?"observability/signoz":id==="settings"?"settings/interface":id
  history.replaceState(null,"",`#${target}`)
  frontendTelemetry.navigation(target)
}
function readHash(){
  const path=location.hash.slice(1)
  const root=path.split("/")[0]||"dashboard"
  const normalized=root==="overview"?"dashboard":root
  if(nav.value.some(item=>item.id===normalized))activePage.value=normalized
}
async function load(){loading.value=true;error.value="";try{session.value=await managementApi.session();bootstrap.value=session.value.authenticated?await managementApi.bootstrap():null}catch(e){error.value=e instanceof Error?e.message:String(t("app.unavailable"))}finally{loading.value=false}}
async function login(){error.value="";try{session.value=await managementApi.login(username.value,password.value);password.value="";bootstrap.value=await managementApi.bootstrap();frontendTelemetry.event("auth.login_success")}catch(e){frontendTelemetry.error("auth.login_failure",e);error.value=e instanceof Error?e.message:"Invalid username or password"}}
async function logout(){session.value=await managementApi.logout();bootstrap.value=null;frontendTelemetry.event("auth.logout")}
function toggleTheme(){theme.value=theme.value==="dark"?"light":"dark"}
function systemNotification(event:BusEvent){const data=(event.data??{}) as Record<string,unknown>;const level=(["info","success","warning","error"].includes(String(data.level))?String(data.level):"info") as NotificationLevel;notifications.push({level,title:String(data.title??"System notification"),description:typeof data.description==="string"?data.description:undefined})}
onMounted(()=>{readHash();window.addEventListener("hashchange",readHash);unsubscribeNotifications=eventBus.subscribe("system.notifications",systemNotification);load()})
onBeforeUnmount(()=>{window.removeEventListener("hashchange",readHash);unsubscribeNotifications?.()})
</script>
<template>
  <ToastHost />
  <div v-if="loading" class="grid min-h-screen place-items-center bg-background text-sm text-muted-foreground">{{t('app.loading')}}</div>
  <div v-else-if="!session?.authenticated" class="grid min-h-screen place-items-center bg-muted/30 p-6"><section class="w-full max-w-sm rounded-xl border border-border bg-card p-6 shadow-sm"><h1 class="text-xl font-semibold">{{t('app.title')}}</h1><p class="mt-1 text-sm text-muted-foreground">{{t('app.console')}}</p><form class="mt-6 space-y-4" @submit.prevent="login"><label class="block space-y-1.5 text-sm"><span>{{t('app.username')}}</span><input v-model="username" autocomplete="username" class="field" /></label><label class="block space-y-1.5 text-sm"><span>{{t('app.password')}}</span><input v-model="password" type="password" autocomplete="current-password" class="field" /></label><p v-if="error" class="text-sm text-destructive">{{error}}</p><Button class="w-full" type="submit">{{t('app.signIn')}}</Button></form></section></div>
  <div v-else-if="bootstrap" class="grid min-h-screen bg-background text-foreground" :class="sidebarCollapsed?'grid-cols-[68px_1fr]':'grid-cols-[240px_1fr]'">
    <aside class="sticky top-0 h-screen border-r border-border bg-sidebar p-3"><div class="mb-5 flex h-10 items-center justify-between"><div v-if="!sidebarCollapsed" class="px-2 font-semibold tracking-tight">{{t('app.title')}}</div><Button variant="ghost" size="icon" @click="sidebarCollapsed=!sidebarCollapsed"><PanelLeftOpen v-if="sidebarCollapsed" class="size-4"/><PanelLeftClose v-else class="size-4"/></Button></div><nav class="space-y-1"><button v-for="item in nav" :key="item.id" class="flex h-9 w-full items-center gap-3 rounded-md px-3 text-sm transition" :class="activePage===item.id?'bg-accent text-foreground':'text-muted-foreground hover:bg-accent hover:text-foreground'" :title="sidebarCollapsed?item.label:undefined" @click="select(item.id)"><component :is="item.icon" class="size-4 shrink-0"/><span v-if="!sidebarCollapsed">{{item.label}}</span></button></nav></aside>
    <main class="min-w-0"><header class="sticky top-0 z-20 flex h-14 items-center border-b border-border bg-background/90 px-6 backdrop-blur"><div class="text-sm text-muted-foreground">{{current.label}}</div><div class="ml-auto flex items-center gap-2"><RealtimeStatus/><span class="mr-2 text-xs text-muted-foreground">{{session.username}}</span><Button variant="ghost" size="icon" @click="toggleTheme"><Sun v-if="theme==='dark'" class="size-4"/><Moon v-else class="size-4"/></Button><Button variant="outline" size="sm" @click="logout">{{t('app.signOut')}}</Button></div></header><div class="mx-auto max-w-[1600px] p-6"><component :is="current.component" /></div></main>
  </div>
  <div v-else class="grid min-h-screen place-items-center bg-background p-6 text-sm text-destructive">{{error||t('app.unavailable')}}</div>
</template>
