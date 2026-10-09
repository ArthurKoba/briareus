<script setup lang="ts">
import { computed, ref, watch } from "vue"
import { useI18n } from "vue-i18n"
import { canonicalUuid4, type AgentSessionRequestView, type AgentSessionView, type SessionSnapshot } from "@/features/platform/model/contracts"
import { useCommand, useDomain } from "@/features/platform/model/use-domain"
import { projectContext } from "@/features/platform/model/project-context"
import { platformPort } from "@/features/platform/api/port"
import PlatformFeedback from "@/features/platform/ui/PlatformFeedback.vue"
import ConfirmAction from "@/features/platform/ui/ConfirmAction.vue"
import Button from "@/shared/ui/Button.vue"
import PageHeader from "@/shared/ui/PageHeader.vue"

const { t }=useI18n()
const sessions=useDomain<SessionSnapshot>("sessions","sessions.read",async(port,ctx)=>({items:[await port.sessions.list(ctx)]}),["project"])
const command=useCommand(["project"])
const data=computed(()=>sessions.state.items[0])
const currentProject=computed(()=>projectContext.state.activeProjectKey)
const openSupported=computed(()=>platformPort.value?.capabilities?.normalSessionOpen===true)
const labelSupported=computed(()=>platformPort.value?.capabilities?.sessionLabels===true)
const elevatedOpenSupported=computed(()=>platformPort.value?.capabilities?.elevatedSessionOpen===true)
const ttlEditSupported=computed(()=>platformPort.value?.capabilities?.sessionApprovalTtlEdit===true)
const requestedTtlMax=computed(()=>Math.min(300,data.value?.elevatedMaxSeconds??0))
const approvalTtlUnchanged=computed(()=>{
  // A4 approvals have second-level source timestamps but datetime-local
  // inputs round to minutes. Do not misclassify that formatting loss as an
  // attempted TTL edit; keep original deadline unmodified on wire.
  if(!ttlEditSupported.value)return approvalUntil.value===""
  const original=reviewing.value?.requestedUntil
  if(!original)return !approvalUntil.value
  return !approvalUntil.value||Date.parse(approvalUntil.value)===Date.parse(original)
})
const rows=computed(()=>data.value?.sessions.filter(session=>session.projectId===currentProject.value && canonicalUuid4(session.sessionUuid))??[])
const requests=computed(()=>data.value?.requests.filter(request=>request.projectId===currentProject.value && canonicalUuid4(request.sessionUuid))??[])
const grantOptions=computed(()=>data.value?.availableGrants??[])
const newLabel=ref("")
const policy=ref<"fixed" | "requestable">("requestable")
const sessionKind=ref<"normal" | "elevated">("normal")
const selectedUuid=ref("")
const selectedGrants=ref<string[]>([])
const requestedUntil=ref("")
const approvalGrants=ref<string[]>([])
const approvalUntil=ref("")
const confirmExpansion=ref(false)
const approvedUntilValid=computed(()=>!approvalUntil.value || Date.parse(approvalUntil.value)>Date.now())
const unknownRequestedGrants=computed(()=>reviewing.value?.requestedGrants.filter(id=>!grantOptions.value.some(option=>option.id===id))??[])
const reviewedGrantsKnown=computed(()=>unknownRequestedGrants.value.length===0)
const beyondRequest=computed(()=>{
  const request=reviewing.value
  if(!request)return false
  if(approvalGrants.value.some(grant=>!request.requestedGrants.includes(grant)))return true
  if(approvalUntil.value && (!request.requestedUntil || Date.parse(approvalUntil.value)>Date.parse(request.requestedUntil)))return true
  return false
})
function toLocalDate(iso: string | null):string {
  if(!iso)return ""
  const date=new Date(iso)
  if(Number.isNaN(date.getTime()))return ""
  return new Date(date.getTime()-date.getTimezoneOffset()*60000).toISOString().slice(0,16)
}
function askResolve(request:AgentSessionRequestView,approve:boolean){
  if(!can("sessions.resolve") || request.allowedActions?.["sessions.resolve"]!==true ||
     request.status!=="pending" || request.projectId!==currentProject.value ||
     !canonicalUuid4(request.sessionUuid))return
  confirmExpansion.value=false
  approvalGrants.value=request.requestedGrants.filter(id=>grantOptions.value.some(option=>option.id===id))
  approvalUntil.value=ttlEditSupported.value?toLocalDate(request.requestedUntil):""
  if (approve) { reviewing.value=request; pending.value=null }
  else { reviewing.value=null; pending.value={kind:"approval",request,approve:false} }
}
function confirmReviewedApproval() {
  if (!reviewing.value || !approvedUntilValid.value || !reviewedGrantsKnown.value || (beyondRequest.value && !confirmExpansion.value) || !approvalTtlUnchanged.value) return
  pending.value={kind:"approval",request:reviewing.value,approve:true}
}
const reviewing=ref<AgentSessionRequestView | null>(null)
const pending=ref<{ kind:"revoke"; session:AgentSessionView } | { kind:"approval"; request:AgentSessionRequestView; approve:boolean } | null>(null)
const can=projectContext.can
const grantSelectionValid=computed(()=>selectedGrants.value.length>0 && selectedGrants.value.every(id=>grantOptions.value.some(item=>item.id===id)))
const untilValid=computed(()=>!requestedUntil.value || (requestedTtlMax.value>0 && Date.parse(requestedUntil.value)>Date.now() && Date.parse(requestedUntil.value)<=Date.now()+requestedTtlMax.value*1000))
watch(()=>projectContext.state.revision,()=>{pending.value=null;reviewing.value=null;newLabel.value="";selectedUuid.value="";selectedGrants.value=[];requestedUntil.value="";approvalGrants.value=[];approvalUntil.value="";confirmExpansion.value=false})
// Any server refresh/WS invalidate replaces the list: a pending confirmation
// created from an older revision must not be silently applied to the new list.
watch(()=>sessions.state.items,()=>{
  const previous=reviewing.value
  if(previous && !requests.value.some(item=>item.id===previous.id&&item.snapshotKey===previous.snapshotKey&&item.status==="pending"))reviewing.value=null
  const action=pending.value
  if(action?.kind==="approval" && !requests.value.some(item=>item.id===action.request.id&&item.snapshotKey===action.request.snapshotKey&&item.status==="pending"))pending.value=null
  if(action?.kind==="revoke" && !rows.value.some(item=>item.sessionUuid===action.session.sessionUuid&&item.revision===action.session.revision&&item.status==="active"))pending.value=null
})

async function openSession(){
  if(!openSupported.value || !currentProject.value || (labelSupported.value&&!newLabel.value.trim()) || (sessionKind.value==="elevated" && !elevatedOpenSupported.value))return
  const created=await command.submit("sessions.open",(port,ctx)=>port.sessions.open(ctx,{label:labelSupported.value?newLabel.value.trim():"",kind:sessionKind.value,elevationPolicy:policy.value}),"session.open")
  if(created){newLabel.value="";await sessions.reload()}
}
async function requestElevation(){
  if(!canonicalUuid4(selectedUuid.value) || !rows.value.some(item=>item.sessionUuid===selectedUuid.value && item.status==="active" && item.elevationPolicy==="requestable") || !grantSelectionValid.value || !untilValid.value)return
  const until=requestedUntil.value ? new Date(requestedUntil.value).toISOString():null
  const requested=await command.submit("sessions.request",(port,ctx)=>port.sessions.request(ctx,{sessionUuid:selectedUuid.value,grants:[...selectedGrants.value],requestedUntil:until}),`session.elevation:${selectedUuid.value}`)
  if(requested){selectedGrants.value=[];requestedUntil.value="";await sessions.reload()}
}
async function resolve(){
  const item=pending.value
  if(!item || (item.kind==="approval" && (item.request.status!=="pending" || item.request.projectId!==currentProject.value || !requests.value.some(row=>row.id===item.request.id&&row.snapshotKey===item.request.snapshotKey&&row.status==="pending"))) || (item.kind==="revoke" && !rows.value.some(row=>row.sessionUuid===item.session.sessionUuid&&row.revision===item.session.revision&&row.status==="active")) || (item.kind==="approval" && item.approve && (!approvedUntilValid.value || !approvalTtlUnchanged.value || !reviewedGrantsKnown.value || (beyondRequest.value && !confirmExpansion.value) || !approvalGrants.value.every(id=>grantOptions.value.some(grant=>grant.id===id)))))return
  const done=await command.submit(item.kind==="revoke" ? "sessions.revoke" : "sessions.resolve",(port,ctx)=>{
    if(item.kind==="revoke")return port.sessions.revoke(ctx,item.session)
    // Server is authoritative for requested grants, expanded grants, TTL and audit.
    const until=item.approve && approvalUntil.value ? new Date(approvalUntil.value).toISOString() : item.request.requestedUntil
    return port.sessions.resolve(ctx,item.request,item.approve,item.approve?[...approvalGrants.value]:[],until,{explicitExpansion:item.approve && beyondRequest.value && confirmExpansion.value})
  },item.kind==="revoke"?`session.revoke:${item.session.sessionUuid}`:`session.resolve:${item.request.id}`)
  if(done){pending.value=null;reviewing.value=null;await sessions.reload()}
}
</script>
<template>
  <div class="space-y-6">
    <PageHeader :title="t('platform.agentSessions')" :description="t('platform.sessionsHint')"><Button variant="outline" size="sm" :disabled="!can('sessions.read')" @click="sessions.reload">{{t('common.refresh')}}</Button></PageHeader>
    <section class="settings-card space-y-3"><h2 class="font-semibold">{{t('platform.openSession')}}</h2><p class="text-xs text-muted-foreground">{{t('platform.sessionBoundaries')}}</p><p v-if="!openSupported" role="status" class="text-xs text-muted-foreground">{{t('platform.sessionOpenPending')}}</p><p v-else-if="!labelSupported" role="status" class="text-xs text-muted-foreground">{{t('platform.unnamedSessionSource')}}</p><form class="flex flex-wrap items-end gap-3" @submit.prevent="openSession"><label v-if="labelSupported" class="min-w-48 flex-1 text-xs">{{t('platform.sessionLabel')}}<input v-model="newLabel" class="field mt-1" maxlength="120" :disabled="!can('sessions.open') || (command.state.busy || command.state.reconciliationRequired)" required /></label><label class="text-xs">{{t('platform.sessionKind')}}<select v-model="sessionKind" class="field mt-1" :disabled="!can('sessions.open') || (command.state.busy || command.state.reconciliationRequired)"><option value="normal">{{t('platform.normalSession')}}</option><option value="elevated" :disabled="!elevatedOpenSupported">{{t('platform.elevatedSession')}}</option></select></label><label class="text-xs">{{t('platform.elevationPolicy')}}<select v-model="policy" class="field mt-1" :disabled="!can('sessions.open') || (command.state.busy || command.state.reconciliationRequired)"><option value="requestable">{{t('platform.requestable')}}</option><option value="fixed">{{t('platform.fixed')}}</option></select></label><Button type="submit" size="sm" :disabled="!can('sessions.open') || !openSupported || (sessionKind==='elevated' && !elevatedOpenSupported) || (command.state.busy || command.state.reconciliationRequired) || (labelSupported && !newLabel.trim())">{{t('platform.open')}}</Button></form></section>
    <section class="settings-card space-y-3"><h2 class="font-semibold">{{t('platform.projectSessions')}}</h2><PlatformFeedback :status="sessions.state.status" :error="sessions.state.error" @retry="sessions.reload" /><p v-if="sessions.state.status==='ready' && !rows.length" class="text-sm text-muted-foreground">{{t('platform.empty')}}</p>
      <div v-if="rows.length" class="overflow-x-auto"><table class="w-full min-w-[650px] text-left text-sm"><thead class="text-xs text-muted-foreground"><tr><th class="py-2">{{t('platform.sessionLabel')}}</th><th>UUIDv4</th><th>{{t('platform.grants')}}</th><th>{{t('platform.expiration')}}</th><th>{{t('common.actions')}}</th></tr></thead><tbody><tr v-for="session in rows" :key="session.sessionUuid" class="border-t border-border"><td class="py-3"><span class="font-medium">{{session.label}}</span><span class="block text-xs text-muted-foreground">{{session.elevation}} · {{session.status}}</span></td><td class="font-mono text-xs" :title="t('platform.uuidPrivate')">{{session.sessionUuid.slice(0,8)}}…</td><td class="text-xs">{{session.grants.join(', ') || '—'}}</td><td class="text-xs">{{session.expiresAt}}</td><td><Button variant="destructive" size="sm" :disabled="!can('sessions.revoke') || session.allowedActions?.['sessions.revoke']!==true || session.status!=='active' || (command.state.busy || command.state.reconciliationRequired)" @click="pending={kind:'revoke',session}">{{t('platform.revoke')}}</Button></td></tr></tbody></table></div>
    </section>
    <section class="settings-card space-y-3"><h2 class="font-semibold">{{t('platform.requestGrants')}}</h2><p class="text-xs text-muted-foreground">{{t('platform.grantHint')}}</p>
      <form class="grid gap-3 sm:grid-cols-2" @submit.prevent="requestElevation"><label class="text-xs">{{t('platform.session')}}<select v-model="selectedUuid" class="field mt-1" :disabled="!can('sessions.request') || (command.state.busy || command.state.reconciliationRequired)"><option value="">{{t('platform.selectSession')}}</option><option v-for="session in rows.filter(item=>item.status==='active' && item.elevationPolicy==='requestable')" :key="session.sessionUuid" :value="session.sessionUuid">{{session.label}} · {{session.sessionUuid.slice(0,8)}}</option></select></label><label class="text-xs">{{t('platform.requestedUntil')}}<input v-model="requestedUntil" class="field mt-1" type="datetime-local" :disabled="!can('sessions.request') || (command.state.busy || command.state.reconciliationRequired)" /></label>
        <fieldset class="sm:col-span-2" :disabled="!can('sessions.request') || (command.state.busy || command.state.reconciliationRequired)"><legend class="mb-2 text-xs">{{t('platform.grants')}}</legend><p v-if="!grantOptions.length" class="text-xs text-muted-foreground">{{t('platform.noGrantSchema')}}</p><div v-for="grant in grantOptions" :key="grant.id" class="mb-1"><label class="inline-flex items-start gap-2 text-xs"><input v-model="selectedGrants" type="checkbox" :value="grant.id" class="mt-0.5" /><span><strong>{{grant.label}}</strong><span v-if="grant.description" class="block text-muted-foreground">{{grant.description}}</span></span></label></div></fieldset>
        <div class="sm:col-span-2"><Button type="submit" size="sm" :disabled="!can('sessions.request') || (command.state.busy || command.state.reconciliationRequired) || !selectedUuid || !grantSelectionValid || !untilValid">{{t('platform.requestApproval')}}</Button><p v-if="!untilValid" role="alert" class="mt-2 text-xs text-destructive">{{t('platform.futureDate')}}</p></div>
      </form>
    </section>
    <section class="settings-card space-y-3"><h2 class="font-semibold">{{t('platform.pendingApprovals')}}</h2><p class="text-xs text-muted-foreground">{{t('platform.anyMemberApprove')}}</p><p v-if="sessions.state.status==='ready' && !requests.length" class="text-sm text-muted-foreground">{{t('platform.empty')}}</p><p v-if="sessions.state.status==='ready' && (rows.length>=250 || requests.length>=250)" role="status" class="rounded-md border border-border bg-muted/20 p-3 text-xs text-muted-foreground">{{t('platform.sessionListLimit')}}</p>
      <div v-for="request in requests" :key="request.id" class="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-border p-3"><div class="min-w-0 text-sm"><strong>{{request.requestedBy}}</strong><p class="mt-1 text-xs text-muted-foreground">{{request.status}} · {{request.sessionUuid.slice(0,8)}}… · {{request.requestedGrants.join(', ')}}</p><p class="mt-1 font-mono text-[10px] text-muted-foreground">{{t('platform.approvalRequestId')}}: {{request.id}}</p><p v-if="request.status==='pending' && request.blockReason" class="mt-1 text-xs text-destructive" role="status">{{t(`platform.approvalBlocked.${request.blockReason}`)}}</p></div><div v-if="request.status==='pending'" class="flex gap-2"><Button size="sm" :disabled="!can('sessions.resolve') || request.allowedActions?.['sessions.resolve']!==true || (command.state.busy || command.state.reconciliationRequired)" @click="askResolve(request,true)">{{t('platform.approve')}}</Button><Button size="sm" variant="outline" :disabled="!can('sessions.resolve') || request.allowedActions?.['sessions.resolve']!==true || (command.state.busy || command.state.reconciliationRequired)" @click="askResolve(request,false)">{{t('platform.reject')}}</Button></div></div>
    </section>
    <section v-if="reviewing" class="settings-card space-y-3"><h2 class="font-semibold">{{t('platform.reviewApproval')}}</h2><p class="text-xs text-muted-foreground">{{t('platform.approvalScopeWarning')}}</p>
      <p v-if="unknownRequestedGrants.length" role="alert" class="text-sm text-destructive">{{t('platform.unknownSessionGrants')}}</p>
      <fieldset><legend class="mb-2 text-xs">{{t('platform.grants')}}</legend><label v-for="grant in grantOptions" :key="grant.id" class="mb-2 flex items-start gap-2 text-xs"><input v-model="approvalGrants" type="checkbox" :value="grant.id" :disabled="(command.state.busy || command.state.reconciliationRequired)" /><span>{{grant.label}}</span></label></fieldset>
      <label v-if="ttlEditSupported" class="block max-w-xs text-xs">{{t('platform.requestedUntil')}}<input v-model="approvalUntil" class="field mt-1" type="datetime-local" :disabled="(command.state.busy || command.state.reconciliationRequired)" /></label>
      <div v-else class="max-w-xl text-xs"><span class="text-muted-foreground">{{t('platform.requestedUntil')}}</span><p class="mt-1 rounded-md border border-border p-2 font-mono">{{reviewing.requestedUntil??'—'}}</p><p class="mt-1 text-muted-foreground">{{t('platform.serverTtlUneditable')}}</p></div>
      <p v-if="!approvedUntilValid" role="alert" class="text-xs text-destructive">{{t('platform.futureDate')}}</p>
      <label v-if="beyondRequest" class="flex items-start gap-2 text-xs text-destructive"><input v-model="confirmExpansion" type="checkbox" :disabled="(command.state.busy || command.state.reconciliationRequired)" /><span>{{t('platform.expansionAcknowledgement')}}</span></label>
      <div class="flex gap-2"><Button size="sm" :disabled="!can('sessions.resolve') || (command.state.busy || command.state.reconciliationRequired) || !approvedUntilValid || !reviewedGrantsKnown || !approvalTtlUnchanged || (beyondRequest && !confirmExpansion)" @click="confirmReviewedApproval">{{t('platform.confirmReviewedApproval')}}</Button><Button variant="outline" size="sm" @click="reviewing=null">{{t('common.cancel')}}</Button></div>
    </section>
    <PlatformFeedback status="idle" :action-error="command.state.error" :reconciled="command.state.reconciliationNotice" :busy="command.state.busy" @reconcile="command.reconcile" />
    <ConfirmAction :open="!!pending" :busy="command.state.busy" :title="t('platform.confirmDanger')" :detail="t('platform.grantDanger')" :target="pending?.kind==='revoke' ? pending.session.sessionUuid : pending?.request.id ?? ''" @cancel="pending=null" @confirm="resolve" />
  </div>
</template>
