<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue"
import { useI18n } from "vue-i18n"
import { knownPlatformPage, platformNavigation } from "@/features/platform"
import type { PlatformPageId } from "@/features/platform/types"
import { ControlPanelShell } from "@/widgets/control-panel"
import ControlPanelAccessPage from "@/pages/platform/ControlPanelAccessPage.vue"
import ModuleWorkspacePage from "@/pages/modules/ModuleWorkspacePage.vue"
import PlatformSettingsPage from "@/pages/platform/PlatformSettingsPage.vue"
import { DashboardOverview } from "@/widgets/dashboard"
import { CatalogWorkspace } from "@/widgets/catalog"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/shared/ui/card"
import { Badge } from "@/shared/ui/badge"
import { Button } from "@/shared/ui/button"
import { Skeleton } from "@/shared/ui/skeleton"
import { Input } from "@/shared/ui/input"
import { FilePreviewPane } from "@/features/files-preview"
import { ApprovalQueue, CurrentAgentSessions, OpenNormalSession } from "@/widgets/platform-context"
import BrowserTabsFixture from "./BrowserTabsFixture.vue"

/** Local DEV-only layout workbench: no bearer, no owner calls, no grants.
 * Enables only nonprivileged presentation and permanently disabled operations.
 */
const { t, locale }=useI18n()
const page=ref<PlatformPageId>("home")
const moduleId=ref("web")
const localText=ref("")
const localFileName=ref("")
const localFileBusy=ref(false)
const localFileError=ref(false)
const showsFileDemo=computed(()=>page.value==="mcp"&&moduleId.value==="files")
const showsBrowserDemo=computed(()=>page.value==="mcp"&&moduleId.value==="web")
const visualState=ref<"empty"|"loading"|"denied"|"unavailable">("empty")
const captions=computed(()=>locale.value==="ru"?{
  preview:"Локальное дизайн-превью",
  reminder:"Только макет и безопасные состояния. Нет серверной авторизации, данных и выполняемых команд.",
  empty:"Нет подтверждённых записей",
  loading:"Загрузка данных",
  denied:"Доступ к этому разделу не подтверждён",
  unavailable:"Сервис временно недоступен",
  states:"Состояние",demo:"Локальный пример предпросмотра файла",fileNote:"Только выбранный файл этого браузера; никаких сетевых загрузок, записей или прав",fileFailed:"Невозможно прочитать выбранный файл.",
  visual:"Визуальная проверка",
  version:"Функциональные элементы активируются только после реального Backend-контракта.",
}:{
  preview:"Local design preview",
  reminder:"Layout and safe states only. No server authentication, data or executable commands.",
  empty:"No verified records",
  loading:"Loading data",
  denied:"Access to this area is not verified",
  unavailable:"Service unavailable",
  states:"State",demo:"Local file preview sample",fileNote:"Selected browser file only. No network upload, writes or permissions.",fileFailed:"The selected file could not be read.",
  visual:"Visual review",
  version:"Functional controls activate only after a verified Backend contract.",
})
const heading=computed(()=>{
  const entry=platformNavigation.find(item=>item.id===page.value)
  return t(`platform.navigation.${entry?.title??"home"}`)
})
function sync():void{
  const [root,id]=window.location.hash.replace(/^#/,"").split("/")
  page.value=root==="platform"&&knownPlatformPage(id??"")?id as PlatformPageId:"home"
  const selected=window.location.hash.split("/")[2]
  moduleId.value=typeof selected==="string"?selected:"web"

}
async function localFile(event:Event):Promise<void>{
  const input=event.target as HTMLInputElement
  localText.value=""
  localFileName.value=""
  localFileError.value=false
  const file=input.files?.[0]
  if(!file)return
  localFileBusy.value=true
  try {
    // A DEV fixture only; display a bounded excerpt, never send it over HTTP.
    const content=await file.slice(0,65537).text()
    localText.value=content
    localFileName.value=file.name
  }catch{localFileError.value=true}
  finally{localFileBusy.value=false}
}
watch(page,()=>{visualState.value="empty"})
watch([page,moduleId],()=>{
  if(!showsFileDemo.value){
    // Browser-selected local text must not persist across preview routes.
    localText.value=""
    localFileName.value=""
    localFileError.value=false
  }
})
onMounted(()=>{
  sync()
  window.addEventListener("hashchange",sync)
  window.addEventListener("popstate",sync)
})
onBeforeUnmount(()=>{
  localText.value=""
  localFileName.value=""
  window.removeEventListener("hashchange",sync)
  window.removeEventListener("popstate",sync)
})
</script>
<template>
  <ControlPanelShell :page="page" :heading="heading" :authenticated="false" design-preview>
    <div class="mb-5 flex flex-wrap items-center justify-between gap-3 rounded-lg border border-border bg-muted/30 px-4 py-3">
      <div class="min-w-0">
        <Badge variant="outline">{{captions.preview}}</Badge>
        <p class="mt-2 text-xs leading-5 text-muted-foreground">{{captions.reminder}}</p>
      </div>
      <code class="rounded-md bg-muted px-3 py-2 text-xs">DEV ONLY</code>
    </div>
    <div v-if="page==='dashboard'||page==='sessions'" class="mb-4 flex flex-wrap items-center gap-2 rounded-lg border border-border bg-card p-3" role="group" :aria-label="captions.states">
      <span class="mr-2 text-xs font-semibold text-muted-foreground">{{captions.states}}</span>
      <Button v-for="state in (['empty','loading','denied','unavailable'] as const)" :key="state" type="button" size="sm"
        :variant="visualState===state?'default':'outline'" :aria-pressed="visualState===state"
        @click="visualState=state">{{captions[state]}}</Button>
    </div>
    <ControlPanelAccessPage v-if="page==='home'" design-preview />
    <div v-else-if="page==='mcp'" class="space-y-5">
      <ModuleWorkspacePage />
      <BrowserTabsFixture v-if="showsBrowserDemo" />
      <Card v-if="showsFileDemo" class="border-dashed">
        <CardHeader>
          <CardTitle class="text-sm">{{captions.demo}}</CardTitle>
          <CardDescription>{{captions.fileNote}}</CardDescription>
        </CardHeader>
        <CardContent class="space-y-4">
          <Input type="file" accept="text/*,.txt,.json,.md,.csv,.log,.yaml,.yml" @change="localFile" />
          <p v-if="localFileError" class="text-xs text-destructive" role="alert">{{captions.fileFailed}}</p>
          <FilePreviewPane :status="localFileBusy?'loading':localFileError?'unavailable':localFileName?'ready':'empty'"
            :path="localFileName" :content="localText" design-preview />
        </CardContent>
      </Card>
    </div>
    <PlatformSettingsPage v-else-if="page==='settings'" />
    <DashboardOverview v-else-if="page==='dashboard'" :state="visualState" />
    <CatalogWorkspace v-else-if="page==='integrations'" kind="integration" design-preview :preview-state="visualState"/>
    <CatalogWorkspace v-else-if="page==='variables'" kind="variable" design-preview :preview-state="visualState"/>
    <div v-else-if="page==='sessions'" class="space-y-4">
      <OpenNormalSession design-preview />
      <CurrentAgentSessions design-preview :preview-state="visualState" />
      <ApprovalQueue design-preview :preview-state="visualState" />
    </div>
    <Card v-else>
      <CardHeader>
        <CardTitle>{{heading}}</CardTitle>
        <CardDescription>{{captions.version}}</CardDescription>
      </CardHeader>
      <CardContent class="space-y-5">
        <div class="flex flex-wrap items-center gap-2" role="group" :aria-label="captions.states">
          <Button v-for="state in (['empty','loading','denied','unavailable'] as const)"
            :key="state" type="button" size="sm"
            :variant="visualState===state?'default':'outline'" :aria-pressed="visualState===state"
            @click="visualState=state">{{captions[state]}}</Button>
        </div>
        <div class="min-h-64 rounded-xl border border-dashed border-border p-5">
          <div v-if="visualState==='loading'" class="space-y-3" role="status">
            <Skeleton class="h-6 w-48" />
            <Skeleton v-for="index in 4" :key="index" class="h-10 w-full" />
          </div>
          <div v-else class="grid min-h-48 place-items-center text-center text-sm text-muted-foreground" role="status">
            <p>{{captions[visualState]}}</p>
          </div>
        </div>
      </CardContent>
    </Card>
  </ControlPanelShell>
</template>
