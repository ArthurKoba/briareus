<script setup lang="ts">
import { computed, onBeforeUnmount, reactive, ref, watch } from "vue"
import { useI18n } from "vue-i18n"
import { projectContext } from "@/features/platform/model/project-context"
import { refreshAuthenticatedProjection } from "@/features/platform/model/refresh-identity"
import { platformPort } from "@/features/platform/api/port"
import { useCommand, useDomain } from "@/features/platform/model/use-domain"
import { providerAuthTypes, providerCatalog, sourceProviderOptions, validResourceAlias, type SourceProviderName } from "@/features/platform/model/provider-options"
import type { ProjectAccountInput, ProjectAccountView, ResourceOwner, ResourceScope, UiCapability } from "@/features/platform/model/contracts"
import PlatformFeedback from "@/features/platform/ui/PlatformFeedback.vue"
import ScopedResourcePicker from "@/features/platform/ui/ScopedResourcePicker.vue"
import ConfirmAction from "@/features/platform/ui/ConfirmAction.vue"
import AppDialog from "@/shared/ui/AppDialog.vue"
import Button from "@/shared/ui/Button.vue"
import PageHeader from "@/shared/ui/PageHeader.vue"

const {t}=useI18n()
const selectedProject=computed(()=>projectContext.state.projects.find(project=>project.key===projectContext.state.activeProjectKey))
const selectedTeamId=computed(()=>projectContext.state.scope==="team"?projectContext.state.activeTeamKey:selectedProject.value?.ownerTeamId??null)
const scopeFilter=ref<ResourceScope>("all")
const readScope=computed<ResourceScope>(()=>projectContext.state.scope==="team"?"team":scopeFilter.value)
type PublishedProvider={provider:string;authTypes:string[];connectivityStatus:string}
const publishedProviders=useDomain<PublishedProvider>(
  "providers","accounts.read",async(port,ctx)=>{
    if(!port.providers)throw new Error("A5 private provider catalog is unavailable")
    const result=await port.providers.catalog(ctx)
    // A5's network_verification_available is FALSE; a true flag would need
    // separate independent reviewer and a new verified Backend API.
    if(result.networkVerificationAvailable)throw new Error("Unreviewed provider verification capability")
    return {items:result.providers}
  },["team","project"],port=>Boolean(port.providers),
)
function catalogStatus(provider:string):string {
  return publishedProviders.state.items.find(item=>item.provider===provider)?.connectivityStatus??""
}
const accounts=useDomain<ProjectAccountView>("accounts","accounts.read",async(port,ctx)=>{
  if(ctx.scope.kind!=="project" && ctx.scope.kind!=="team")throw new Error("Resource scope required")
  const chosen=readScope.value
  const result=await port.accounts.list(ctx,{scope:chosen})
  const invalid=result.items.some(item=>{
    if(chosen==="team"&&item.owner.kind!=="team")return true
    if(chosen==="project"&&item.owner.kind!=="project")return true
    if(ctx.scope.kind==="team")return item.visibleIn.kind!=="team"||item.visibleIn.teamId!==ctx.scope.teamId||item.owner.kind!=="team"||item.owner.teamId!==ctx.scope.teamId||item.inherited
    if(item.visibleIn.kind!=="project"||item.visibleIn.projectId!==ctx.scope.projectId)return true
    if(item.owner.kind==="project")return item.owner.projectId!==ctx.scope.projectId||item.inherited
    return item.owner.teamId!==selectedTeamId.value||!item.inherited
  })
  if(invalid)throw new Error("Scoped resource provenance mismatch")
  return result // Keep BOTH equal aliases. Never merge by name or prefer Project.
},["project","team"])
watch(scopeFilter,()=>{void accounts.reload()})
const command=useCommand(["project","team"])
const can=projectContext.can
const ownerKind=ref<"project"|"team">("project")
const providerFilter=ref<"all"|ProjectAccountView["provider"]>("all")
const providers=Object.keys(providerCatalog) as SourceProviderName[]
const visible=computed(()=>accounts.state.items.filter(item=>providerFilter.value==="all"||item.provider===providerFilter.value))
const choices=computed(()=>visible.value.map(item=>({id:item.id,name:`${item.provider}:${item.alias}`,owner:item.owner})))
const mode=ref<null|"create"|"rename"|"rotate">(null)
const editing=ref<ProjectAccountView|null>(null)
const form=reactive({
  provider:"github" as SourceProviderName,alias:"",authType:"personal_token",baseUrl:"",displayName:"",
  installationId:"",organization:"",namespace:"",tenant:"",credential:"",
})
const toDelete=ref<ProjectAccountView|null>(null)
const confirmRotate=ref(false)
const localNotice=ref("")
const canManageTeam=computed(()=>Boolean(selectedTeamId.value&&can("accounts.teamManage")))
const canCreate=computed(()=>projectContext.state.scope==="team"?canManageTeam.value:can("accounts.manage")||canManageTeam.value)
const requestedOwner=computed<ResourceOwner|null>(()=>{
  if(editing.value)return editing.value.owner
  if(projectContext.state.scope==="team"||ownerKind.value==="team")return selectedTeamId.value?{kind:"team",teamId:selectedTeamId.value}:null
  return projectContext.state.activeProjectKey?{kind:"project",projectId:projectContext.state.activeProjectKey}:null
})
const actionFor=(owner:ResourceOwner):UiCapability=>owner.kind==="team"?"accounts.teamManage":"accounts.manage"
function canManage(item:ProjectAccountView):boolean {
  const action=actionFor(item.owner)
  return can(action)&&item.allowedActions?.[action]===true
}
const mayWrite=computed(()=>Boolean(requestedOwner.value&&can(actionFor(requestedOwner.value))&&(!editing.value||canManage(editing.value))))
const authTypes=computed(()=>providerAuthTypes(form.provider))
const settings=computed(()=>sourceProviderOptions(form))
const catalogAllows=computed(()=>publishedProviders.state.items.some(item=>
  item.provider===form.provider && item.authTypes.includes(form.authType) && item.connectivityStatus==="unverified"))
const valid=computed(()=>{
  if(!mayWrite.value||!validResourceAlias(form.alias))return false
  if(mode.value==="create")return Boolean(catalogAllows.value&&settings.value&&form.credential.length>0)
  if(mode.value==="rename")return Boolean(editing.value&&form.alias.trim()!==editing.value.alias)
  if(mode.value==="rotate")return Boolean(editing.value&&form.credential.length>0)
  return false
})
const verifyingAvailable=computed(()=>Boolean(platformPort.value?.capabilities?.candidateVerification))

function resetSensitive():void {
  form.credential=""
  form.installationId=""
  form.organization=""
  form.namespace=""
  form.tenant=""
}
function closeForm():void {
  // Closing a form only discards local inputs. The cross-page command fence
  // survives, so uncertainty must never trap secrets in a modal dialog.
  if(command.state.busy)return
  resetSensitive()
  mode.value=null
  editing.value=null
  localNotice.value=""
}
function begin(next:"create"|"rename"|"rotate",account?:ProjectAccountView):void {
  if(next==="create"&&!canCreate.value)return
  if(next!=="create"&&(!account||!canManage(account)))return
  editing.value=account??null
  ownerKind.value=account?.owner.kind??(projectContext.state.scope==="team"||(!can("accounts.manage")&&canManageTeam.value)?"team":"project")
  resetSensitive()
  form.provider=(account?.provider??"github") as SourceProviderName
  form.authType=account?.authType??providerAuthTypes(form.provider)[0]??""
  form.alias=account?.alias??""
  form.baseUrl="" // The draft ResourceView does NOT return provider_settings.
  form.displayName=""
  mode.value=next
  localNotice.value=""
}
watch(()=>form.provider,()=>{if(!authTypes.value.includes(form.authType))form.authType=authTypes.value[0]??""})
const unsubscribe=projectContext.onTransition(()=>{
  resetSensitive();mode.value=null;editing.value=null;toDelete.value=null;confirmRotate.value=false
  ownerKind.value="project";scopeFilter.value="all";localNotice.value=""
})
onBeforeUnmount(()=>{unsubscribe();resetSensitive()})

async function createOrRename():Promise<void> {
  const owner=requestedOwner.value
  if(!owner||!valid.value||(command.state.busy || command.state.reconciliationRequired)||mode.value==="rotate")return
  const currentMode=mode.value
  const input:ProjectAccountInput={owner,provider:form.provider,alias:form.alias.trim(),baseUrl:form.baseUrl,
    ...(currentMode==="create"?{authType:form.authType,providerSettings:settings.value??undefined,credential:form.credential}:{}),
    ...(editing.value?{expectedRevision:editing.value.revision}:{})}
  const done=await command.submit(actionFor(owner),(port,ctx)=>port.accounts.save(ctx,input,editing.value?.id),
    projectContext.state.scope==="project"&&owner.kind==="project" ? (editing.value?"integration.update":"integration.create") : null)
  // Credentials never persist after a failed or uncertain mutation.
  resetSensitive()
  if(done){closeForm();await refreshAuthenticatedProjection();await accounts.reload()}
}
function askRotate():void {
  if(mode.value!=="rotate"||!valid.value)return
  confirmRotate.value=true
}
async function rotate():Promise<void> {
  const account=editing.value
  if(!account||!canManage(account)||!form.credential.trim())return
  const credential=form.credential
  const done=await command.submit(actionFor(account.owner),(port,ctx)=>port.accounts.rotate(ctx,account,credential),
    projectContext.state.scope==="project"&&account.owner.kind==="project"?"integration.rotate":null)
  resetSensitive()
  confirmRotate.value=false
  if(done){closeForm();await refreshAuthenticatedProjection();await accounts.reload()}
}
async function remove():Promise<void> {
  const account=toDelete.value
  if(!account||!canManage(account))return
  const done=await command.submit(actionFor(account.owner),(port,ctx)=>port.accounts.remove(ctx,account),
    projectContext.state.scope==="project"&&account.owner.kind==="project"?"integration.revoke":null)
  if(done){toDelete.value=null;await refreshAuthenticatedProjection();await accounts.reload()}
}
</script>
<template>
  <div class="space-y-6">
    <PageHeader :title="t('platform.integrations')" :description="t('platform.effectiveIntegrationsHint')">
      <Button variant="outline" size="sm" :disabled="!can('accounts.read')" @click="accounts.reload">{{t('common.refresh')}}</Button>
      <Button size="sm" :disabled="!canCreate" @click="begin('create')">{{t('accounts.add')}}</Button>
    </PageHeader>
    <p class="rounded-lg border border-border bg-muted/30 p-3 text-xs text-muted-foreground">{{t('platform.scopeCollisionRule')}}</p>
    <section class="settings-card space-y-2">
      <h2 class="text-sm font-semibold">{{t('platform.a5ProviderCatalog')}}</h2>
      <p class="text-xs text-muted-foreground">{{t('platform.providerConnectivityNotTested')}}</p>
      <PlatformFeedback :status="publishedProviders.state.status" :error="publishedProviders.state.error" @retry="publishedProviders.reload" />
      <div v-if="publishedProviders.state.items.length" class="flex flex-wrap gap-2">
        <span v-for="item in publishedProviders.state.items" :key="item.provider" class="rounded-md border border-border px-2 py-1 text-xs">
          {{item.provider}} · {{item.connectivityStatus}} · {{item.authTypes.join(', ')}}
        </span>
      </div>
    </section>
    <section class="settings-card space-y-3">
      <label v-if="projectContext.state.scope==='project'" class="block max-w-xs text-xs">{{t('platform.resourceReadScope')}}
        <select v-model="scopeFilter" class="field mt-1"><option value="all">{{t('platform.scopeAll')}}</option><option v-if="selectedTeamId" value="team">{{t('platform.scopeTeam')}}</option><option value="project">{{t('platform.scopeProject')}}</option></select>
      </label>
      <p v-else class="text-xs text-muted-foreground">{{t('platform.scopeTeam')}}</p>
      <div class="flex flex-wrap items-center gap-2" :aria-label="t('platform.provider')"><button v-for="provider in (['all',...providers] as const)" :key="provider" type="button" class="rounded-md border border-border px-3 py-1.5 text-xs capitalize" :class="providerFilter===provider?'bg-accent font-medium':'hover:bg-muted'" :aria-pressed="providerFilter===provider" @click="providerFilter=provider">{{provider==='all'?t('platform.allProviders'):provider}}</button></div>
      <ScopedResourcePicker v-if="accounts.state.status==='ready'" :items="choices" :label="t('platform.chooseConnection')" />
      <PlatformFeedback :status="accounts.state.status" :error="accounts.state.error" @retry="accounts.reload" />
      <p v-if="accounts.state.status==='ready'&&!visible.length" class="p-3 text-sm text-muted-foreground">{{t('platform.empty')}}</p>
      <div v-if="visible.length" class="overflow-x-auto"><table class="w-full min-w-[720px] text-left text-sm"><thead class="text-xs text-muted-foreground"><tr><th class="py-2">{{t('platform.provider')}}</th><th>{{t('accounts.alias')}}</th><th>{{t('platform.sourceOwner')}}</th><th>{{t('common.status')}}</th><th>{{t('common.actions')}}</th></tr></thead>
        <tbody><tr v-for="account in visible" :key="`${account.visibleIn.kind}:${account.owner.kind}:${account.id}`" class="border-t border-border">
          <td class="py-3 capitalize">{{account.provider}}</td><td><div class="font-medium">{{account.alias}}</div><span class="block font-mono text-[10px] text-muted-foreground" :title="account.id">{{t('platform.resourceId')}}: {{account.id.slice(0,12)}}…</span><div v-if="account.baseUrl" class="max-w-64 truncate text-xs text-muted-foreground" :title="account.baseUrl">{{account.baseUrl}}</div><span v-if="account.updatedAt" class="block text-[10px] text-muted-foreground">{{account.updatedAt}}</span><span class="text-xs text-muted-foreground">{{account.credentialConfigured===null?t('platform.notPublished'):account.credentialConfigured?t('platform.secretConfigured'):t('platform.secretMissing')}}</span></td>
          <td><div class="text-xs">{{account.owner.kind==='team'?t('platform.teamOwned'):t('platform.projectOwned')}}</div><span class="block text-xs text-muted-foreground">{{account.inherited?t('platform.inherited'):t('platform.directResource')}}</span><span class="block font-mono text-[10px] text-muted-foreground" :title="account.owner.kind==='team'?account.owner.teamId:account.owner.projectId">{{(account.owner.kind==='team'?account.owner.teamId:account.owner.projectId).slice(0,12)}}…</span></td>
          <td>{{account.connectionStatus==='unverified'?t('platform.providerUnverified'):t('platform.notPublished')}}</td>
          <td><div class="flex flex-wrap gap-1"><Button size="sm" variant="outline" :disabled="!canManage(account)" @click="begin('rename',account)">{{t('platform.renameResource')}}</Button><Button size="sm" variant="outline" :disabled="!canManage(account)" @click="begin('rotate',account)">{{t('platform.rotateCredential')}}</Button><Button size="sm" variant="destructive" :disabled="!canManage(account)" @click="toDelete=account">{{t('platform.revoke')}}</Button></div></td>
        </tr></tbody></table></div>
    </section>
    <AppDialog :open="!!mode" :title="mode==='create'?t('accounts.addTitle'):mode==='rename'?t('platform.renameResource'):t('platform.rotateCredential')" width="620px" @close="closeForm">
      <form class="space-y-4" @submit.prevent="mode==='rotate'?askRotate():createOrRename()">
        <label class="block text-xs">{{t('platform.sourceOwner')}}<select v-model="ownerKind" class="field mt-1" :disabled="mode!=='create'||(command.state.busy || command.state.reconciliationRequired)"><option v-if="projectContext.state.scope==='project'" value="project">{{t('platform.projectOwned')}}</option><option v-if="selectedTeamId&&canManageTeam" value="team">{{t('platform.teamOwned')}}</option></select></label>
        <label class="block text-xs">{{t('platform.provider')}}<select v-model="form.provider" class="field mt-1" :disabled="mode!=='create'||(command.state.busy || command.state.reconciliationRequired)"><option v-for="provider in providers" :key="provider" :value="provider" :disabled="!publishedProviders.state.items.some(item=>item.provider===provider)">{{provider}} · {{catalogStatus(provider)||t('platform.notPublished')}}</option></select></label>
        <label v-if="mode!=='rotate'" class="block text-xs">{{t('accounts.alias')}}<input v-model="form.alias" class="field mt-1" maxlength="128" required :disabled="(command.state.busy || command.state.reconciliationRequired)" /></label>
        <template v-if="mode==='create'">
          <label class="block text-xs">{{t('platform.authType')}}<select v-model="form.authType" class="field mt-1" :disabled="(command.state.busy || command.state.reconciliationRequired)"><option v-for="auth in authTypes" :key="auth" :value="auth">{{auth}}</option></select></label>
          <label class="block text-xs">{{t('accounts.baseUrl')}}<input v-model="form.baseUrl" class="field mt-1" inputmode="url" maxlength="2048" placeholder="https://" :disabled="(command.state.busy || command.state.reconciliationRequired)" /></label>
          <label class="block text-xs">{{t('platform.displayName')}}<input v-model="form.displayName" class="field mt-1" maxlength="128" :disabled="(command.state.busy || command.state.reconciliationRequired)" /></label>
          <label v-if="form.provider==='github'&&form.authType==='github_app'" class="block text-xs">{{t('platform.installationId')}}<input v-model="form.installationId" class="field mt-1" inputmode="numeric" :disabled="(command.state.busy || command.state.reconciliationRequired)" /></label>
          <label v-if="form.provider==='github'" class="block text-xs">{{t('platform.organization')}}<input v-model="form.organization" class="field mt-1" maxlength="128" :disabled="(command.state.busy || command.state.reconciliationRequired)" /></label>
          <label v-if="form.provider==='gitlab'" class="block text-xs">{{t('platform.namespace')}}<input v-model="form.namespace" class="field mt-1" maxlength="128" :disabled="(command.state.busy || command.state.reconciliationRequired)" /></label>
          <label v-if="!['github','gitlab'].includes(form.provider)" class="block text-xs">{{t('platform.tenant')}}<input v-model="form.tenant" class="field mt-1" maxlength="128" :disabled="(command.state.busy || command.state.reconciliationRequired)" /></label>
        </template>
        <label v-if="mode==='rotate'||mode==='create'" class="block text-xs">{{t('accounts.credential')}}<input v-model="form.credential" class="field mt-1" type="password" autocomplete="new-password" :disabled="(command.state.busy || command.state.reconciliationRequired)" required /></label>
        <p v-if="editing" class="text-xs text-muted-foreground">{{t('platform.resourceOwnerImmutable')}}</p><p class="text-xs text-muted-foreground">{{mode==='rename'?t('platform.sourceRenameHint'):t('platform.credentialHint')}}</p>
        <p v-if="!verifyingAvailable&&mode==='create'" class="text-xs text-muted-foreground">{{t('platform.connectionCheckPending')}}</p>
        <p v-if="!valid" role="status" class="text-xs text-destructive">{{t('platform.accountValidation')}}</p>
        <p v-if="localNotice" role="status" class="text-xs text-muted-foreground">{{localNotice}}</p>
        <PlatformFeedback status="idle" :action-error="command.state.error" :reconciled="command.state.reconciliationNotice" :busy="command.state.busy" @reconcile="command.reconcile" />
      </form>
      <template #footer><Button variant="outline" :disabled="command.state.busy" @click="closeForm">{{t('common.cancel')}}</Button><Button :disabled="!valid||(command.state.busy || command.state.reconciliationRequired)" @click="mode==='rotate'?askRotate():createOrRename()">{{mode==='rotate'?t('platform.reviewRotation'):t('common.save')}}</Button></template>
    </AppDialog>
    <ConfirmAction :open="confirmRotate" :busy="command.state.busy" :title="t('platform.rotateCredential')" :detail="t('platform.teamResourceDeleteHint')" :target="editing?.id??''" @cancel="confirmRotate=false" @confirm="rotate" />
    <ConfirmAction :open="!!toDelete" :busy="command.state.busy" :title="t('platform.confirmDanger')" :detail="t('platform.teamResourceDeleteHint')" :target="toDelete?.id??''" @cancel="toDelete=null" @confirm="remove" />
    <PlatformFeedback status="idle" :action-error="command.state.error" :reconciled="command.state.reconciliationNotice" :busy="command.state.busy" @reconcile="command.reconcile" />
  </div>
</template>
