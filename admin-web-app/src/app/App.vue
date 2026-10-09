<script setup lang="ts">
import { computed, defineAsyncComponent, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue"
import { Menu, Moon, PanelLeftClose, PanelLeftOpen, Sun, X } from "lucide-vue-next"
import { useI18n } from "vue-i18n"
import { adminApi, type AdminBootstrap, type SessionState } from "@/shared/api/admin"
import { bindLegacyRequestBoundary, invalidateLegacyRequests } from "@/shared/api/legacy-client"
import { platformPort } from "@/features/platform/api/port"
import { accountStore } from "@/features/accounts/model/account-store"
import { projectContext } from "@/features/platform/model/project-context"
import ContextSwitcher from "@/features/platform/ui/ContextSwitcher.vue"
import { callStore } from "@/pages/calls/model/call-store"
import { settingsStore } from "@/shared/settings/store"
import { useUiPreferences } from "@/shared/lib/preferences"
import { frontendTelemetry } from "@/shared/telemetry/client"
import { eventBus, type BusEvent } from "@/shared/events/bus"
import { notifications, type NotificationLevel } from "@/shared/notifications/bus"
import { validPlatformPage, type PlatformPageId } from "@/app/platform-navigation"
import PlatformNav from "@/app/PlatformNav.vue"
import PublicAccountPage from "@/pages/platform/PublicAccountPage.vue"
import ScopedRealtimeStatus from "@/features/platform/ui/ScopedRealtimeStatus.vue"
import Button from "@/shared/ui/Button.vue"
import RealtimeStatus from "@/shared/ui/RealtimeStatus.vue"
import SidebarNav from "@/shared/ui/SidebarNav.vue"
import ToastHost from "@/shared/notifications/ToastHost.vue"

const legacyPages = {
  dashboard: defineAsyncComponent(() => import("@/pages/dashboard/DashboardPage.vue")),
  git: defineAsyncComponent(() => import("@/pages/git/GitPage.vue")),
  observability: defineAsyncComponent(() => import("@/pages/observability/ObservabilityPage.vue")),
  calls: defineAsyncComponent(() => import("@/pages/calls/CallsPage.vue")),
  files: defineAsyncComponent(() => import("@/pages/files/FilesPage.vue")),
  terminal: defineAsyncComponent(() => import("@/pages/terminal/TerminalPage.vue")),
  browser: defineAsyncComponent(() => import("@/pages/browser/BrowserPage.vue")),
  analysis: defineAsyncComponent(() => import("@/pages/analysis/AnalysisPage.vue")),
  access: defineAsyncComponent(() => import("@/pages/access/AccessPage.vue")),
  oauth: defineAsyncComponent(() => import("@/pages/oauth/OAuthPage.vue")),
  settings: defineAsyncComponent(() => import("@/pages/settings/SettingsPage.vue")),
}
type LegacyPageId = keyof typeof legacyPages
const platformPages: Record<PlatformPageId, ReturnType<typeof defineAsyncComponent>> = {
  home: defineAsyncComponent(() => import("@/pages/platform/PlatformHomePage.vue")),
  users: defineAsyncComponent(() => import("@/pages/platform/UsersPage.vue")),
  teams: defineAsyncComponent(() => import("@/pages/platform/TeamsPage.vue")),
  projects: defineAsyncComponent(() => import("@/pages/platform/ProjectsPage.vue")),
  agents: defineAsyncComponent(() => import("@/pages/platform/AgentsPage.vue")),
  sessions: defineAsyncComponent(() => import("@/pages/platform/AgentSessionsPage.vue")),
  integrations: defineAsyncComponent(() => import("@/pages/platform/ProjectAccountsPage.vue")),
  variables: defineAsyncComponent(() => import("@/pages/platform/ProjectVariablesPage.vue")),
  dashboard: defineAsyncComponent(() => import("@/pages/platform/ResourceBoundaryPage.vue")),
  calls: defineAsyncComponent(() => import("@/pages/platform/ResourceBoundaryPage.vue")),
  oauth: defineAsyncComponent(() => import("@/pages/platform/ResourceBoundaryPage.vue")),
  files: defineAsyncComponent(() => import("@/pages/platform/ResourceBoundaryPage.vue")),
  terminal: defineAsyncComponent(() => import("@/pages/platform/ResourceBoundaryPage.vue")),
  "browser-managed": defineAsyncComponent(() => import("@/pages/platform/ResourceBoundaryPage.vue")),
  "browser-external": defineAsyncComponent(() => import("@/pages/platform/ResourceBoundaryPage.vue")),
  analysis: defineAsyncComponent(() => import("@/pages/platform/ResourceBoundaryPage.vue")),
  settings: defineAsyncComponent(() => import("@/pages/platform/PlatformSettingsPage.vue")),
}
const resourcePageTitle: Partial<Record<PlatformPageId, string>> = {
  dashboard:"dashboard",calls:"calls",oauth:"oauth",files:"files",terminal:"terminal",analysis:"analysis",
  "browser-managed":"browserManaged","browser-external":"browserExternal",
}
const {t}=useI18n()
const session=ref<SessionState | null>(null)
const bootstrap=ref<AdminBootstrap | null>(null)
const loading=ref(true)
const submitting=ref(false)
const gatewayUnavailable=ref(false)
const error=ref("")
const username=ref("")
const password=ref("")
const legacyPage=ref<LegacyPageId>("dashboard")
const routePage=ref("home")
const platformHash=ref(false)
const mobileNavOpen=ref(false)
const mobileNavPanel=ref<HTMLElement|null>(null)
const publicFlow=ref<"invitation"|"reset"|null>(null)
const publicToken=ref("")
const publicLinkError=ref(false)
const {theme,sidebarCollapsed}=useUiPreferences()
// If the new platform contract was ever loaded, never fall back to legacy privileges.
const platformRequired=ref(Boolean(platformPort.value))
const legacyScope=computed(()=>projectContext.state.scope==="legacy")
const verifiedScope=computed(()=>["choose-project","team","project","operator"].includes(projectContext.state.scope) && Boolean(projectContext.state.user?.active))
const signedIn=computed(()=>legacyScope.value ? session.value?.authenticated===true : verifiedScope.value)
const platformMode=computed(()=>verifiedScope.value || (legacyScope.value && platformHash.value))
const platformPreview=computed(()=>legacyScope.value && platformHash.value)
const activePlatformPage=computed<PlatformPageId>(()=>validPlatformPage(routePage.value,platformPreview.value)?routePage.value:"home")
const title=computed(()=>platformMode.value?t(`platform.navigation.${resourcePageTitle[activePlatformPage.value]??activePlatformPage.value}`):t(`nav.${legacyPage.value}`))
const currentComponent=computed(()=>platformMode.value?platformPages[activePlatformPage.value]:legacyPages[legacyPage.value])
let authGeneration=0
let currentAuthController:AbortController | null=null
let unsubscribeNotifications:(()=>void)|undefined
let unsubscribeContext:(()=>void)|undefined
let unsubscribeCredential:(()=>void)|undefined
let unbindLegacyBoundary:(()=>void)|undefined

function invalidateLegacyData() {
  frontendTelemetry.setLegacySessionActive(false)
  notifications.clearAll()
  eventBus.setSessionActive(false)
  accountStore.setSessionActive(false)
  callStore.setSessionActive(false)
  settingsStore.setSessionActive(false)
}
function rememberLegacy(next:SessionState) {
  session.value=next
  if(next.authenticated){
    projectContext.beginLegacySession()
    const legacyDataAllowed=!platformHash.value && !publicFlow.value
    frontendTelemetry.setLegacySessionActive(legacyDataAllowed)
    eventBus.setSessionActive(legacyDataAllowed)
    accountStore.setSessionActive(legacyDataAllowed)
    callStore.setSessionActive(legacyDataAllowed)
    settingsStore.setSessionActive(legacyDataAllowed)
  }else projectContext.clear()
}
function expireAuth(){
  ++authGeneration
  // Invalidating a pending restore must not strand the shell in a permanent
  // loading spinner: the old load() finally belongs to a stale generation.
  loading.value=false
  gatewayUnavailable.value=false
  submitting.value=false
  currentAuthController?.abort()
  invalidateLegacyData()
  session.value=null
  bootstrap.value=null
  projectContext.clear()
  password.value=""
  publicToken.value=""
}
/** Real Identity source uses ?invite= or ?reset=; scrub one-use keys immediately. */
function readOneUseLink(): void {
  const url = new URL(location.href)
  const invite = url.searchParams.get("invite")
  const reset = url.searchParams.get("reset")
  if (invite === null && reset === null) return
  publicLinkError.value = false
  url.searchParams.delete("invite")
  url.searchParams.delete("reset")
  history.replaceState(null,"",`${url.pathname}${url.search}${url.hash}`)
  // An ambiguous link MUST NOT choose one token or flow silently.
  if (invite !== null && reset !== null) {
    publicLinkError.value = true
    publicToken.value = ""
    publicFlow.value = null
    return
  }
  publicToken.value = invite ?? reset ?? ""
  publicFlow.value = invite !== null ? "invitation" : "reset"
}
function closePublicFlow(): void { publicFlow.value=null;publicToken.value="";publicLinkError.value=false }
function readBrowserHistory():void {
  // History navigation can restore an old ?invite= or ?reset= query even
  // after initial mount; scrub it before any route/telemetry processing.
  readOneUseLink()
  readHash()
}
function readHash(){
  const path=location.hash.slice(1)
  const [root,child]=path.split("/")
  platformHash.value=root==="platform"
  routePage.value=platformHash.value?child||"home":"home"
  const normalized=root==="overview"?"dashboard":root
  if(Object.prototype.hasOwnProperty.call(legacyPages,normalized))legacyPage.value=normalized as LegacyPageId
  mobileNavOpen.value=false
}
function openMobileNav():void { mobileNavOpen.value=true }
function closeMobileNav():void { mobileNavOpen.value=false }
watch(mobileNavOpen, async open=>{
  await nextTick()
  if(open){
    const focusable=mobileNavPanel.value?.querySelector<HTMLElement>("nav button:not(:disabled)")
    ;(focusable??mobileNavPanel.value)?.focus()
  }else if(window.matchMedia("(max-width: 767px)").matches &&
            mobileNavPanel.value?.contains(document.activeElement)){
    // Do not steal focus after history navigation or unrelated header action.
    // Restore the opener only if focus was still trapped inside the panel.
    document.getElementById("mobile-nav-trigger")?.focus()
  }
})
function handleMobileNavKey(event:KeyboardEvent):void {
  if(!mobileNavOpen.value||window.matchMedia("(min-width: 768px)").matches)return
  if(event.key==="Escape"){
    event.preventDefault()
    closeMobileNav()
    return
  }
  if(event.key!=="Tab"||!mobileNavPanel.value)return
  const focusable=[...mobileNavPanel.value.querySelectorAll<HTMLElement>(
    "button:not(:disabled), a[href], select:not(:disabled), [tabindex]:not([tabindex='-1'])",
  )].filter(item=>item.getClientRects().length>0)
  const first=focusable[0],last=focusable[focusable.length-1]
  if(!first||!last){event.preventDefault();mobileNavPanel.value.focus();return}
  if(event.shiftKey&&(document.activeElement===first||!mobileNavPanel.value.contains(document.activeElement))){
    event.preventDefault();last.focus()
  }else if(!event.shiftKey&&(document.activeElement===last||!mobileNavPanel.value.contains(document.activeElement))){
    event.preventDefault();first.focus()
  }
}
function handleSidebarClick(event:MouseEvent):void {
  if(!mobileNavOpen.value)return
  if(event.target instanceof Element && event.target.closest("nav button"))closeMobileNav()
}
function ensurePlatformRoute(){
  if(verifiedScope.value && !platformHash.value){
    history.replaceState(null,"",`${location.pathname}${location.search}#platform/home`)
    readHash()
  }
}
async function load(){
  const generation=++authGeneration
  currentAuthController?.abort()
  const controller=new AbortController()
  currentAuthController=controller
  loading.value=true
  error.value=""
  gatewayUnavailable.value=false
  try{
    const adapter=platformPort.value
    if(adapter){
      const projection=await adapter.auth.restore(controller.signal)
      if(generation!==authGeneration)return
      bootstrap.value=null
      session.value=projection?{authenticated:true,username:projection.user.username}:null
      if(projection)projectContext.installServerProjection(projection)
      else projectContext.clear()
      ensurePlatformRoute()
    }else if(platformRequired.value){
      throw new Error("Verified platform adapter unavailable")
    }else{
      const next=await adminApi.session()
      if(generation!==authGeneration)return
      rememberLegacy(next)
      const details = next.authenticated && !platformHash.value && !publicFlow.value
        ? await adminApi.bootstrap() : null
      if (generation !== authGeneration) return
      bootstrap.value = details
    }
  }catch{
    if(generation!==authGeneration)return
    // Moving to Preview during old bootstrap aborts its global read, but
    // does not invalidate an already authenticated legacy operator session.
    if(legacyScope.value && session.value?.authenticated &&
       (platformHash.value || publicFlow.value)){
      bootstrap.value=null
      return
    }
    gatewayUnavailable.value=true
    error.value=String(t("app.unavailable"))
    session.value=null
    bootstrap.value=null
    // A browser-local remembered username NEVER verifies an unavailable backend.
    projectContext.offline()
  }finally{if(generation===authGeneration){loading.value=false;currentAuthController=null}}
}
async function login(){
  if(submitting.value)return
  const generation=++authGeneration
  currentAuthController?.abort()
  const controller=new AbortController()
  currentAuthController=controller
  submitting.value=true
  error.value=""
  try{
    const adapter=platformPort.value
    if(adapter){
      const projection=await adapter.auth.login({username:username.value,password:password.value},controller.signal)
      if(generation!==authGeneration)return
      session.value={authenticated:true,username:projection.user.username}
      projectContext.installServerProjection(projection)
      ensurePlatformRoute()
    }else if(platformRequired.value){
      throw new Error("Verified platform adapter unavailable")
    }else{
      const next=await adminApi.login(username.value,password.value)
      if(generation!==authGeneration)return
      rememberLegacy(next)
      const details = next.authenticated && !platformHash.value && !publicFlow.value
        ? await adminApi.bootstrap() : null
      if (generation !== authGeneration) return
      bootstrap.value=details
    }
    password.value=""
    gatewayUnavailable.value=false
    frontendTelemetry.event("auth.login_success")
  }catch(caught){
    if(generation!==authGeneration)return
    frontendTelemetry.event("auth.login_failure")
    error.value=String(t("platform.signInFailed"))
  }finally{
    if(generation===authGeneration){
      // Password is never retained in a failed/expired browser login form.
      password.value=""
      submitting.value=false
      currentAuthController=null
    }
  }
}
async function logout(){
  if(submitting.value)return
  submitting.value=true
  error.value=""
  try{
    const adapter=platformPort.value
    if(adapter)await adapter.auth.logout(new AbortController().signal)
    else if(!platformRequired.value)await adminApi.logout()
  }catch{
    // Local data is still purged; next sign-in MUST validate the server.
    error.value=String(t("platform.logoutUncertain"))
  }finally{
    expireAuth()
    submitting.value=false
    frontendTelemetry.event("auth.logout")
  }
}
function systemNotification(event:BusEvent){
  if (!legacyScope.value || platformPreview.value || platformRequired.value || !session.value?.authenticated) return
  const data=(event.data??{}) as Record<string,unknown>
  const level=(["info","success","warning","error"].includes(String(data.level))?String(data.level):"info") as NotificationLevel
  notifications.push({level,title:String(data.title??"System notification"),description:typeof data.description==="string"?data.description:undefined})
}
function observeVerifiedCredential():void {
  unsubscribeCredential?.()
  unsubscribeCredential=platformPort.value?.auth.onCredentialInvalidated?.(()=>{
    // Token revocation/expiry invalidates every Project and Team snapshot.
    // No stored cookie/username is ever used to restore platform rights.
    expireAuth()
  })
}
watch(platformPort, adapter => {
  observeVerifiedCredential()
  if (adapter) platformRequired.value=true
  // A changed transport is a new trust boundary: purge, then re-authenticate.
  expireAuth()
  void load()
})
watch([platformPreview,publicFlow], ([preview,oneUseFlow]) => {
  if (!legacyScope.value || !session.value?.authenticated) return
  // An explicit one-use registration/reset view must not receive legacy
  // account-store notifications while it is open on an existing session.
  if (preview || oneUseFlow) {
    invalidateLegacyRequests()
    invalidateLegacyData()
  } else if (!submitting.value) {
    // Return from Preview/one-use verifies the existing OLD operator session
    // and rehydrates legacy stores; it NEVER authenticates a Project User.
    void load()
  }
})
watch([verifiedScope,routePage,platformHash,()=>projectContext.state.revision],()=>{
  if(verifiedScope.value){ensurePlatformRoute();if(!validPlatformPage(routePage.value)){history.replaceState(null,"",`${location.pathname}${location.search}#platform/home`);readHash()}}
})
onMounted(()=>{
  observeVerifiedCredential()
  unbindLegacyBoundary=bindLegacyRequestBoundary(()=>({
    legacy:projectContext.state.scope==="legacy" && !platformHash.value && !publicFlow.value,
    legacyLogout:projectContext.state.scope==="legacy",
    unauthenticated:["signed-out","offline"].includes(projectContext.state.scope),
    revision:projectContext.state.revision,
  }))
  unsubscribeContext=projectContext.onTransition(()=>{
    invalidateLegacyRequests()
    invalidateLegacyData()
  })
  accountStore.start();callStore.start();settingsStore.start()
  readOneUseLink()
  readHash()
  window.addEventListener("hashchange",readBrowserHistory)
  window.addEventListener("popstate",readBrowserHistory)
  window.addEventListener("keydown",handleMobileNavKey)
  window.addEventListener("admin:auth-expired",expireAuth)
  unsubscribeNotifications=eventBus.subscribe("system.notifications",systemNotification)
  void load()
})
onBeforeUnmount(()=>{
  ++authGeneration;currentAuthController?.abort();invalidateLegacyData()
  unsubscribeContext?.();unsubscribeNotifications?.()
  unbindLegacyBoundary?.()
  unsubscribeCredential?.()
  accountStore.stop();callStore.stop();settingsStore.stop()
  window.removeEventListener("hashchange",readBrowserHistory)
  window.removeEventListener("popstate",readBrowserHistory)
  window.removeEventListener("keydown",handleMobileNavKey)
  window.removeEventListener("admin:auth-expired",expireAuth)
})
</script>
<template>
  <ToastHost />
  <div v-if="loading" role="status" class="grid min-h-screen place-items-center bg-background text-sm text-muted-foreground">{{t('app.loading')}}</div>
  <div v-else-if="gatewayUnavailable" class="grid min-h-screen place-items-center bg-background p-6"><section class="w-full max-w-md rounded-xl border border-border bg-card p-6 text-center shadow-sm"><h1 class="text-lg font-semibold">{{t('app.title')}}</h1><p class="mt-2 text-sm text-muted-foreground">{{t('platform.unverifiedOffline')}}</p><Button class="mt-5" @click="load">{{t('common.retry')}}</Button></section></div>
  <div v-else-if="publicFlow" class="grid min-h-screen place-items-center bg-muted/30 p-6"><PublicAccountPage :key="publicFlow" :mode="publicFlow" :initial-token="publicToken" @token-copied="publicToken=''" @back="closePublicFlow" /></div>
  <div v-else-if="!signedIn" class="grid min-h-screen place-items-center bg-muted/30 p-6"><section class="w-full max-w-sm rounded-xl border border-border bg-card p-6 shadow-sm">
    <h1 class="text-xl font-semibold">{{t('app.title')}}</h1><p class="mt-1 text-sm text-muted-foreground">{{t('app.console')}}</p>
    <div v-if="projectContext.state.scope==='suspended'" class="mt-4 rounded-lg border border-destructive/30 p-3 text-sm text-destructive" role="alert">{{t('platform.suspendedNotice')}}</div>
    <p v-if="publicLinkError" role="alert" class="mt-4 rounded-lg border border-destructive/30 p-3 text-sm text-destructive">{{t('platform.ambiguousPublicLink')}}</p>
    <form class="mt-6 space-y-4" @submit.prevent="login"><label class="block space-y-1.5 text-sm"><span>{{t('app.username')}}</span><input v-model="username" autocomplete="username" class="field" required /></label><label class="block space-y-1.5 text-sm"><span>{{t('app.password')}}</span><input v-model="password" type="password" autocomplete="current-password" class="field" required /></label><p v-if="error" class="text-sm text-destructive" role="alert">{{error}}</p><Button class="w-full" type="submit" :disabled="submitting">{{t('app.signIn')}}</Button></form><div class="mt-4 flex flex-wrap justify-center gap-2"><Button variant="ghost" size="sm" @click="publicFlow='invitation'">{{t('platform.haveInvitation')}}</Button><Button variant="ghost" size="sm" @click="publicFlow='reset'">{{t('platform.haveResetLink')}}</Button></div>
  </section></div>
  <div v-else class="min-h-screen bg-background text-foreground md:grid" :class="sidebarCollapsed?'md:grid-cols-[68px_minmax(0,1fr)]':'md:grid-cols-[240px_minmax(0,1fr)]'">
    <button v-if="mobileNavOpen" class="fixed inset-0 z-30 bg-black/40 md:hidden" :aria-label="t('platform.closeMenu')" tabindex="-1" @click="closeMobileNav" />
    <aside ref="mobileNavPanel" tabindex="-1" :role="mobileNavOpen?'dialog':undefined" :aria-modal="mobileNavOpen?'true':undefined" :aria-label="t('platform.navigation.title')" @click="handleSidebarClick" class="fixed inset-y-0 left-0 z-40 h-screen w-60 overflow-y-auto border-r border-border bg-sidebar p-3 transition-transform md:sticky md:top-0 md:w-auto md:translate-x-0" :class="mobileNavOpen?'translate-x-0':'-translate-x-full'">
      <div class="mb-5 flex h-10 items-center justify-between"><div v-if="!sidebarCollapsed || mobileNavOpen" class="truncate px-2 font-semibold tracking-tight">{{t('app.title')}}</div><Button variant="ghost" size="icon" class="hidden md:inline-flex" :aria-label="t('platform.toggleSidebar')" @click="sidebarCollapsed=!sidebarCollapsed"><PanelLeftOpen v-if="sidebarCollapsed" class="size-4"/><PanelLeftClose v-else class="size-4"/></Button><Button variant="ghost" size="icon" class="md:hidden" :aria-label="t('platform.closeMenu')" @click="closeMobileNav"><X class="size-4"/></Button></div>
      <PlatformNav v-if="platformMode" :collapsed="sidebarCollapsed && !mobileNavOpen" :active-page="activePlatformPage" :preview="platformPreview" />
      <template v-else><SidebarNav :collapsed="sidebarCollapsed && !mobileNavOpen" :active-page="legacyPage"/><button class="mt-5 w-full rounded-md border border-border p-2 text-left text-xs text-muted-foreground hover:bg-accent" @click="location.hash='platform/home'">{{t('platform.openPreview')}}</button></template>
    </aside>
    <main class="min-w-0"><header class="sticky top-0 z-20 flex min-h-14 flex-wrap items-center gap-2 border-b border-border bg-background/95 px-3 py-2 backdrop-blur sm:px-6"><Button id="mobile-nav-trigger" variant="ghost" size="icon" class="md:hidden" :aria-label="t('platform.openMenu')" :aria-expanded="mobileNavOpen" @click="openMobileNav"><Menu class="size-4"/></Button><h1 class="min-w-0 flex-1 truncate text-sm text-muted-foreground">{{title}}</h1><div class="ml-auto flex min-w-0 flex-wrap items-center justify-end gap-2"><ContextSwitcher/><RealtimeStatus v-if="legacyScope && !platformPreview"/><ScopedRealtimeStatus v-else-if="verifiedScope && !platformPreview" /><span class="hidden max-w-32 truncate text-xs text-muted-foreground lg:inline">{{projectContext.state.user?.label??session?.username}}</span><Button variant="ghost" size="icon" :aria-label="t('settings.theme')" @click="theme=theme==='dark'?'light':'dark'"><Sun v-if="theme==='dark'" class="size-4"/><Moon v-else class="size-4"/></Button><Button variant="outline" size="sm" :disabled="submitting" @click="logout">{{t('app.signOut')}}</Button></div></header>
      <div class="mx-auto w-full max-w-[1600px] p-3 sm:p-6"><p v-if="platformPreview" class="mb-4 rounded-lg border border-border bg-muted/30 p-3 text-xs text-muted-foreground" role="status">{{t('platform.previewNotice')}}</p><component :is="currentComponent" :key="`${projectContext.state.revision}:${platformMode?activePlatformPage:legacyPage}`" v-bind="platformMode && resourcePageTitle[activePlatformPage] ? {resource:resourcePageTitle[activePlatformPage]} : {}" /></div>
    </main>
  </div>
</template>
