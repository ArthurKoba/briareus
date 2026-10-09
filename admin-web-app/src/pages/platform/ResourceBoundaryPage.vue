<script setup lang="ts">
import { computed, ref, watch } from "vue"
import { useI18n } from "vue-i18n"
import { FolderOpen, ShieldCheck } from "lucide-vue-next"
import { projectContext } from "@/features/platform/model/project-context"
import type { OperationalArea, OperationalItemView, UiCapability } from "@/features/platform/model/contracts"
import { platformPort } from "@/features/platform/api/port"
import { useDomain } from "@/features/platform/model/use-domain"
import PlatformFeedback from "@/features/platform/ui/PlatformFeedback.vue"
import Button from "@/shared/ui/Button.vue"
import PageHeader from "@/shared/ui/PageHeader.vue"

const props=defineProps<{ resource:OperationalArea }>()
const { t }=useI18n()
const capabilities: Record<OperationalArea, UiCapability> = {
  // A5 only publishes permission-checked DATABASE METADATA, not process I/O.
  dashboard:"operations.metadata.read",files:"operations.metadata.read",
  terminal:"operations.metadata.read",analysis:"operations.metadata.read",
  calls:"calls.read",oauth:"oauth.read",browserManaged:"browser.managed.read",
  browserExternal:"browser.external.read",settings:"settings.read",
}
const a5MetadataAreas=new Set<OperationalArea>(["dashboard","files","terminal","analysis"])
const title=computed(()=>t(`platform.navigation.${props.resource}`))
const project=computed(()=>projectContext.state.projects.find(item=>item.key===projectContext.state.activeProjectKey))
const adapterReady=computed(()=>Boolean(a5MetadataAreas.has(props.resource)&&platformPort.value?.capabilities?.operationalSummary===true && platformPort.value.operations))
const capability=computed(()=>capabilities[props.resource])
const operatorRows=useDomain<OperationalItemView>(
  "operations", capability.value,
  async(port, context)=>{
    if(!port.operations || context.scope.kind!=="project") throw new Error("Scoped read-only adapter not configured")
    const result=await port.operations.list(context,props.resource)
    const projectId=context.scope.projectId
    if(result.items.some(item=>item.projectId!==projectId)) throw new Error("Cross-Project operational response denied")
    return result
  },
  ["project"],
  port=>Boolean(a5MetadataAreas.has(props.resource)&&port.capabilities?.operationalSummary===true && port.operations),
)
const status=computed(()=>operatorRows.state.status)
const search=ref("")
const statusFilter=ref("")
const selectedRecordId=ref("")
const selectedRecord=computed(()=>visibleRows.value.find(item=>item.id===selectedRecordId.value)??null)
const knownStatuses=computed(()=>[...new Set(operatorRows.state.items.map(item=>item.status))].sort())
const visibleRows=computed(()=>{
  const term=search.value.trim().toLocaleLowerCase()
  return operatorRows.state.items.filter(item=>
    (!statusFilter.value || item.status===statusFilter.value) &&
    (!term || `${item.label} ${item.id}`.toLocaleLowerCase().includes(term)),
  )
})
watch(()=>projectContext.state.revision,()=>{search.value="";statusFilter.value="";selectedRecordId.value=""})
watch(()=>operatorRows.state.items,()=>{
  if(selectedRecordId.value && !operatorRows.state.items.some(item=>item.id===selectedRecordId.value))selectedRecordId.value=""
})
</script>
<template>
  <div class="space-y-6">
    <PageHeader :title="title" :description="t('platform.scopedResourceHint')">
      <Button size="sm" variant="outline" :disabled="!adapterReady || !projectContext.can(capability) || operatorRows.state.status==='loading'" @click="operatorRows.reload">{{t('common.refresh')}}</Button>
    </PageHeader>
    <section class="grid gap-3 md:grid-cols-2">
      <div class="settings-card flex items-start gap-3">
        <FolderOpen class="mt-1 size-5 shrink-0 text-muted-foreground" aria-hidden="true" />
        <div class="min-w-0"><h2 class="mb-1 text-sm font-semibold">{{t('platform.projectBoundary')}}</h2><p class="break-words text-sm">{{project?.label??t('context.selectProject')}}</p><p class="mt-1 text-xs text-muted-foreground">{{t('platform.projectBoundaryHint')}}</p></div>
      </div>
      <div class="settings-card flex items-start gap-3">
        <ShieldCheck class="mt-1 size-5 shrink-0 text-muted-foreground" aria-hidden="true" />
        <div class="min-w-0"><h2 class="mb-1 text-sm font-semibold">{{t('platform.authorizationBoundary')}}</h2><p class="text-sm">{{projectContext.can(capability)?t('platform.presentationAllowed'):t('platform.presentationDenied')}}</p><p class="mt-1 text-xs text-muted-foreground">{{t('platform.backendPermissionRequired')}}</p></div>
      </div>
    </section>
    <section class="settings-card space-y-3">
      <h2 class="text-sm font-semibold">{{t('platform.resourceState')}}</h2>
      <p class="text-sm text-muted-foreground">{{t(`platform.operationalHint.${resource}`)}}</p>
      <p v-if="a5MetadataAreas.has(resource)" role="status" class="rounded-md border border-border bg-muted/20 p-3 text-xs text-muted-foreground">{{t('platform.a5LedgerNotRuntime')}}</p>
      <p v-else role="status" class="rounded-md border border-border bg-muted/20 p-3 text-xs text-muted-foreground">{{t('platform.a5AreaUnavailable')}}</p>
      <p v-if="!adapterReady" class="rounded-md border border-border bg-muted/30 p-3 text-sm text-muted-foreground" role="status">{{t('platform.resourceBlocked')}}</p>
      <PlatformFeedback v-else :status="status" :error="operatorRows.state.error" @retry="operatorRows.reload" />
      <p v-if="adapterReady && operatorRows.state.possiblyTruncated" role="status" class="rounded-md border border-border p-3 text-xs text-muted-foreground">{{t('platform.a5LedgerCap', {limit:operatorRows.state.serverLimit??50})}}</p>
      <p v-if="adapterReady && operatorRows.state.observedAt" class="text-xs text-muted-foreground">{{t('platform.a5ObservedAt')}}: {{operatorRows.state.observedAt}}</p>
      <div v-if="status==='ready' && operatorRows.state.items.length" class="flex flex-wrap items-end gap-3">
        <label class="min-w-52 flex-1 text-xs">{{t('platform.filterResource')}}
          <input v-model="search" class="field mt-1" type="search" maxlength="160" :placeholder="t('platform.filterResourcePlaceholder')" />
        </label>
        <label class="min-w-44 text-xs">{{t('common.status')}}
          <select v-model="statusFilter" class="field mt-1"><option value="">{{t('platform.allStatuses')}}</option><option v-for="item in knownStatuses" :key="item" :value="item">{{item}}</option></select>
        </label>
        <span role="status" class="text-xs text-muted-foreground">{{t('platform.visibleCount', {count:visibleRows.length})}}</span>
      </div>
      <p v-if="status==='ready' && operatorRows.state.items.length && !visibleRows.length" class="text-sm text-muted-foreground" role="status">{{t('platform.noMatchingResources')}}</p>
      <div v-if="status==='ready' && visibleRows.length" class="overflow-x-auto">
        <table class="w-full min-w-[450px] text-left text-sm">
          <thead class="text-xs text-muted-foreground"><tr><th class="py-2">{{t('platform.resourceId')}}</th><th>{{t('platform.resourceName')}}</th><th>{{t('common.status')}}</th><th>{{t('platform.a5ObservedAt')}}</th></tr></thead>
          <tbody><tr v-for="item in visibleRows" :key="item.id" class="border-t border-border"><td class="max-w-36 py-3 font-mono text-xs"><button class="max-w-36 truncate text-left underline-offset-2 hover:underline focus-visible:underline" type="button" :aria-pressed="selectedRecordId===item.id" :title="item.id" @click="selectedRecordId=selectedRecordId===item.id?'':item.id">{{item.id}}</button></td><td class="break-words">{{item.label}}</td><td>{{item.status}}</td><td>{{item.observedAt??item.updatedAt??'—'}}</td></tr></tbody>
        </table>
      </div>
      <section v-if="selectedRecord" class="space-y-2 rounded-lg border border-border bg-muted/20 p-4" :aria-label="t('platform.resourceReadOnlyDetails')">
        <h3 class="text-sm font-semibold">{{t('platform.resourceReadOnlyDetails')}}</h3>
        <dl class="grid gap-2 text-xs sm:grid-cols-2">
          <div class="min-w-0"><dt class="text-muted-foreground">{{t('platform.resourceId')}}</dt><dd class="break-all font-mono">{{selectedRecord.id}}</dd></div>
          <div class="min-w-0"><dt class="text-muted-foreground">{{t('platform.resourceName')}}</dt><dd class="break-words">{{selectedRecord.label}}</dd></div>
          <div class="min-w-0"><dt class="text-muted-foreground">{{t('platform.projectBoundary')}}</dt><dd class="break-all font-mono">{{selectedRecord.projectId}}</dd></div>
          <div class="min-w-0"><dt class="text-muted-foreground">{{t('common.status')}}</dt><dd class="break-words">{{selectedRecord.status}}</dd></div>
          <div class="min-w-0"><dt class="text-muted-foreground">{{t('platform.updatedAt')}}</dt><dd>{{selectedRecord.observedAt??selectedRecord.updatedAt??t('platform.notPublished')}}</dd></div>
          <div v-if="selectedRecord.ledgerKind" class="min-w-0"><dt class="text-muted-foreground">{{t('platform.a5LedgerKind')}}</dt><dd>{{selectedRecord.ledgerKind}}</dd></div>
          <div v-if="selectedRecord.version" class="min-w-0"><dt class="text-muted-foreground">{{t('platform.a5RecordVersion')}}</dt><dd class="tabular-nums">{{selectedRecord.version}}</dd></div>
          <div v-if="selectedRecord.hardExpiresAt" class="min-w-0"><dt class="text-muted-foreground">{{t('platform.expiration')}}</dt><dd>{{selectedRecord.hardExpiresAt}}</dd></div>
          <div v-if="selectedRecord.cleanupState" class="min-w-0"><dt class="text-muted-foreground">{{t('platform.a5CleanupState')}}</dt><dd>{{selectedRecord.cleanupState}}</dd></div>
          <div v-if="selectedRecord.reportedStatus" class="min-w-0"><dt class="text-muted-foreground">{{t('platform.a5ReportedState')}}</dt><dd>{{selectedRecord.reportedStatus}}</dd></div>
          <div v-if="selectedRecord.fileCount!==undefined" class="min-w-0"><dt class="text-muted-foreground">{{t('platform.a5FileQuota')}}</dt><dd class="tabular-nums">{{selectedRecord.fileCount}} / {{selectedRecord.usedBytes}} / {{selectedRecord.reservedBytes}} / {{selectedRecord.byteLimit}}</dd></div>
        </dl>
        <p class="text-xs text-muted-foreground">{{t('platform.operationalMetadataOnly')}}</p>
        <Button size="sm" variant="outline" @click="selectedRecordId=''">{{t('common.close')}}</Button>
      </section>
      <p class="text-xs text-muted-foreground">{{t('platform.legacyAvailable')}}</p>
    </section>
  </div>
</template>
