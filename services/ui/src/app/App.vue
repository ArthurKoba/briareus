<script setup lang="ts">
import { computed, defineAsyncComponent, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue"
import { useI18n } from "vue-i18n"
import { platformPort } from "@/features/platform/api/port"
import { projectContext } from "@/features/platform/model/project-context"
import { refreshBffOwnerBoundary } from "@/features/platform/model/refresh-owner-boundary"
import { browserTelemetry } from "@/features/platform/model/browser-telemetry"
import { normalizeUiError } from "@/features/platform/model/errors"
import { validPlatformPage } from "@/features/platform"
import type { PlatformPageId } from "@/features/platform/types"
import { ControlPanelShell } from "@/widgets/control-panel"
import ControlPanelAccessPage from "@/pages/platform/ControlPanelAccessPage.vue"
import OidcPanelPage from "@/pages/platform/OidcPanelPage.vue"
import OperationProgress from "@/features/platform/ui/OperationProgress.vue"
import { Card, CardContent, CardHeader, CardTitle } from "@/shared/ui/card"
import { Button } from "@/shared/ui/button"
import ToastHost from "@/shared/notifications/ToastHost.vue"
const LocalDesignPreview = import.meta.env.DEV
  ? defineAsyncComponent(() => import("@/pages/preview/LocalDesignPreview.vue"))
  : null

/** Module/source loading is separate from authoritative Platform permissions. */
const pages: Record<PlatformPageId, ReturnType<typeof defineAsyncComponent>> = {
  home: defineAsyncComponent(() => import("@/pages/platform/PlatformHomePage.vue")),
  mcp: defineAsyncComponent(() => import("@/pages/modules/ModuleWorkspacePage.vue")),
  users: defineAsyncComponent(() => import("@/pages/platform/UsersPage.vue")),
  teams: defineAsyncComponent(() => import("@/pages/platform/TeamsPage.vue")),
  projects: defineAsyncComponent(() => import("@/pages/platform/ProjectsPage.vue")),
  agents: defineAsyncComponent(() => import("@/pages/platform/AgentsPage.vue")),
  sessions: defineAsyncComponent(() => import("@/pages/platform/AgentSessionsPage.vue")),
  integrations: defineAsyncComponent(() => import("@/pages/platform/ProjectAccountsPage.vue")),
  variables: defineAsyncComponent(() => import("@/pages/platform/ProjectVariablesPage.vue")),
  dashboard: defineAsyncComponent(() => import("@/pages/dashboard/DashboardPage.vue")),
  calls: defineAsyncComponent(() => import("@/pages/platform/ResourceBoundaryPage.vue")),
  oauth: defineAsyncComponent(() => import("@/pages/platform/ResourceBoundaryPage.vue")),
  files: defineAsyncComponent(() => import("@/pages/platform/ResourceBoundaryPage.vue")),
  terminal: defineAsyncComponent(() => import("@/pages/platform/ResourceBoundaryPage.vue")),
  "browser-managed": defineAsyncComponent(() => import("@/pages/platform/ResourceBoundaryPage.vue")),
  "browser-external": defineAsyncComponent(() => import("@/pages/platform/ResourceBoundaryPage.vue")),
  analysis: defineAsyncComponent(() => import("@/pages/platform/ResourceBoundaryPage.vue")),
  settings: defineAsyncComponent(() => import("@/pages/platform/PlatformSettingsPage.vue")),
}
const labels: Partial<Record<PlatformPageId,string>> = {
  "browser-managed": "browserManaged", "browser-external": "browserExternal",
}
const { t }=useI18n()
/** Compile-time DEV gate. This branch is unreachable in production bundles. */
const localDesignPreview = import.meta.env.DEV
  && new URLSearchParams(window.location.search).get("ui-preview") === "1"
const routePage=ref<PlatformPageId>("home")
const verified=computed(()=>projectContext.state.user?.active===true &&
  ["choose-project","project","team","operator"].includes(projectContext.state.scope))
const activePage=computed<PlatformPageId>(()=>verified.value&&validPlatformPage(routePage.value)?routePage.value:"home")
const title=computed(()=>t(`platform.navigation.${labels[activePage.value]??activePage.value}`))
const screen=computed(()=>pages[activePage.value])
const busy=ref(false)
const unavailable=ref(false)
const error=ref("")
let generation=0
let controller:AbortController|null=null
let unsubscribeCredential:(()=>void)|undefined

function clearAuth():void {
  ++generation
  controller?.abort()
  controller=null
  browserTelemetry.clear()
  projectContext.clear()
  busy.value=false
}
function syncHash():void {
  const [root,child]=location.hash.slice(1).split("/")
  // All application surfaces are protected. An anonymous hash is not a role.
  if(root==="platform"&&child&&verified.value&&validPlatformPage(child)){
    routePage.value=child
  }else{
    routePage.value="home"
    if(location.hash!=="#platform/home"){
      history.replaceState(null,"",`${location.pathname}${location.search}#platform/home`)
    }
  }
  browserTelemetry.navigation(activePage.value)
}
async function restore():Promise<void> {
  const current=++generation
  controller?.abort()
  const request=new AbortController()
  controller=request
  unavailable.value=false
  error.value=""
  if(!platformPort.value) {
    // No unverified Rauthy User can activate protected Platform views.
    projectContext.clear()
    browserTelemetry.lifecycle("blocked")
    controller=null
    syncHash()
    return
  }
  busy.value=true
  const port=platformPort.value
  try {
    const projection=await port.auth.restore(request.signal)
    if(current!==generation||request.signal.aborted||port!==platformPort.value)return
    if(!projection||!projection.user.active){
      port.auth.invalidate?.()
      projectContext.clear()
      if(projection&&!projection.user.active)error.value=String(t("platform.suspendedNotice"))
      return
    }
    projectContext.installServerProjection(projection)
    await refreshBffOwnerBoundary()
    if(current!==generation||request.signal.aborted)return
    browserTelemetry.lifecycle("ok")
    syncHash()
  }catch(cause){
    if(current!==generation||request.signal.aborted)return
    const issue=normalizeUiError(cause)
    port.auth.invalidate?.()
    projectContext.clear()
    error.value=String(t(issue.kind==="unauthorized"?"platform.authSessionExpired":"platform.unverifiedOffline"))
    unavailable.value=issue.kind!=="unauthorized"
    browserTelemetry.error("app","authentication")
  }finally {
    if(current===generation){busy.value=false;controller=null}
  }
}
async function logout():Promise<void>{
  if(busy.value)return
  busy.value=true
  const port=platformPort.value
  ++generation
  controller?.abort()
  projectContext.clear()
  try{await port?.auth.logout(new AbortController().signal)}
  catch{error.value=String(t("platform.logoutUncertain"))}
  finally{
    port?.auth.invalidate?.()
    clearAuth()
    syncHash()
  }
}
function onCredentialInvalidated():void {
  clearAuth()
  syncHash()
}
watch(platformPort,()=>{
  if(localDesignPreview)return
  unsubscribeCredential?.()
  unsubscribeCredential=undefined
  clearAuth()
  if(!platformPort.value){
    // The independent OIDC BFF page owns public callback/deep-link routing.
    // An uninstalled legacy PlatformPort must not rewrite its URL.
    window.removeEventListener("hashchange",syncHash)
    window.removeEventListener("popstate",syncHash)
    return
  }
  window.addEventListener("hashchange",syncHash)
  window.addEventListener("popstate",syncHash)
  unsubscribeCredential=platformPort.value.auth.onCredentialInvalidated?.(onCredentialInvalidated)
  void restore()
})
watch(()=>projectContext.state.revision,()=>{
  if(!localDesignPreview&&projectContext.state.user?.active)void refreshBffOwnerBoundary()
})
watch(routePage,async()=>{
  await nextTick()
  document.getElementById("briareus-page-title")?.focus()
})
onMounted(()=>{
  if(localDesignPreview||!platformPort.value)return
  unsubscribeCredential=platformPort.value.auth.onCredentialInvalidated?.(onCredentialInvalidated)
  window.addEventListener("hashchange",syncHash)
  window.addEventListener("popstate",syncHash)
  syncHash()
  void restore()
})
onBeforeUnmount(()=>{
  if(localDesignPreview)return
  clearAuth()
  unsubscribeCredential?.()
  platformPort.value?.auth.invalidate?.()
  window.removeEventListener("hashchange",syncHash)
  window.removeEventListener("popstate",syncHash)
})
</script>

<template>
  <ToastHost />
  <LocalDesignPreview v-if="localDesignPreview" />
  <OidcPanelPage v-else-if="!verified"/>
  <ControlPanelShell v-else :page="activePage" :heading="title" :authenticated="verified" :busy="busy" @logout="logout">
    <div v-if="error" role="alert" class="mb-4 rounded-lg border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive">{{error}}</div>
    <Card v-if="unavailable && verified" class="max-w-lg">
      <CardHeader><CardTitle>{{t('platform.unverifiedOffline')}}</CardTitle></CardHeader>
      <CardContent><Button variant="outline" :disabled="busy" @click="restore">{{t('common.retry')}}</Button></CardContent>
    </Card>
    <ControlPanelAccessPage v-else-if="!verified" />
    <div v-else class="min-w-0">
      <OperationProgress :active-page="activePage" />
      <component :is="screen" :key="`${projectContext.state.revision}:${activePage}`" />
    </div>
  </ControlPanelShell>
</template>
