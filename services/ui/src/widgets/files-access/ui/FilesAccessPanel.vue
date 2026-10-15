<script setup lang="ts">
import {computed,onBeforeUnmount,ref,watch} from "vue"
import {useI18n} from "vue-i18n"
import {filesReadScopes,retainUnexpiredFilesReadScopes,listCurrentSessions,type FilesReadScopeSummary} from "@/features/agent-sessions"
import {readProjectContext,type VerifiedPlatformContext} from "@/features/platform/api/platform-current"
import type {RauthyPanelIdentity} from "@/features/platform/api/rauthy-oidc"
import {useProofLifetime} from "@/shared/lib/use-proof-lifetime"
import {Button} from "@/shared/ui/button"
import {Badge} from "@/shared/ui/badge"
import {Card,CardContent,CardHeader,CardTitle} from "@/shared/ui/card"

/** Only current BFF membership and session READs. No Files private API or
 * actual MCP read is inferred by a displayed resource selector. */
const props=defineProps<{
  identity:RauthyPanelIdentity
  context:VerifiedPlatformContext
  projectId:string
}>()
const {locale}=useI18n()
const state=ref<"idle"|"loading"|"ready"|"denied"|"unavailable"|"expired">("idle")
const scopes=ref<FilesReadScopeSummary[]>([])
const limited=ref(false)
const proofCurrent=useProofLifetime(()=>props.context.expires_at)
// Membership or permissions can change while the parent retains the same
// expiry timestamp. A changed scope must invalidate the old list immediately.
const ownerScope=computed(()=>JSON.stringify([
  props.context.rauthy.issuer,props.context.rauthy.subject,props.context.user.id,
  props.context.projects.find(project=>project.id===props.projectId)??null,
]))
const earliest=computed(()=>scopes.value.length?
  new Date(Math.min(...scopes.value.map(item=>Date.parse(item.expiresAt)))).toISOString():null)
const scopesCurrent=useProofLifetime(()=>earliest.value)
let controller:AbortController|null=null,run=0
const labels=computed(()=>locale.value==="ru"?{
  title:"Files · доступные области сеансов",loading:"Проверяем текущие права и сеансы проекта…",
  denied:"Нет подтверждённого права читать Files-области этого проекта.",
  unavailable:"Сеансы или текущая область проекта недоступны. Содержимое файлов не запрашивается.",
  expired:"Подтверждение доступа или снимок областей истёк. Обновите данные.",
  empty:"Нет активных сеансов с точной областью files.read/read_file. Наличие обычной AgentSession само по себе не даёт такого разрешения.",
  refresh:"Обновить проверку",selector:"Область",revision:"Ревизия",expires:"Истекает",
  limited:"Список BFF ограничен 50 сеансами. Отсутствие области в списке не подтверждает её удаления.",
  boundary:"Это видимые области из Control Panel API. Files Hand отдельно проверяет Cedar, текущую AgentSession и отзыв; файловые операции здесь недоступны.",
}:{
  title:"Files · session-scoped resources",loading:"Verifying current Project and AgentSession permissions…",
  denied:"Current Project scope does not authorize viewing these Files resources.",
  unavailable:"Project or session owner is unavailable. No file contents are requested.",
  expired:"Project proof or displayed resource snapshot expired. Refresh to recheck.",
  empty:"No active AgentSession with an exact files.read/read_file resource. A normal session alone does not authorize it.",
  refresh:"Refresh scope",selector:"Resource",revision:"Revision",expires:"Expires",
  limited:"The BFF inventory is capped at 50 sessions. Absence in the list does not confirm removal.",
  boundary:"These are Control Panel API snapshots. The Files Hand still checks Cedar, the current AgentSession and revocation. File operations are unavailable here.",
})
function cancel():void{++run;controller?.abort();controller=null;scopes.value=[];limited.value=false}
async function refresh():Promise<void>{
  cancel()
  if(!proofCurrent.value){state.value="expired";return}
  if(!props.context.projects.some(p=>p.id===props.projectId&&p.permissions.includes("use_resources"))){state.value="denied";return}
  const request=new AbortController(),generation=++run
  controller=request;state.value="loading"
  const timeout=setTimeout(()=>request.abort(),8000)
  try{
    const owner=await readProjectContext(props.identity,props.projectId,request.signal)
    if(request.signal.aborted||generation!==run)return
    if(owner.kind!=="verified"){
      state.value=owner.kind==="denied"||owner.kind==="not_current"||owner.kind==="signed_out"?"denied":"unavailable"
      return
    }
    if(owner.context.user.id!==props.context.user.id||
      !owner.context.projects.some(p=>p.id===props.projectId&&p.permissions.includes("use_resources"))){state.value="denied";return}
    const canApprove=owner.context.projects.some(p=>p.id===props.projectId&&p.permissions.includes("approve_agent_session"))
    const sessions=await listCurrentSessions(props.projectId,props.context.user.id,canApprove,request.signal)
    if(request.signal.aborted||generation!==run)return
    if(sessions.kind!=="ready"){
      state.value=sessions.kind==="forbidden"||sessions.kind==="unauthorized"?"denied":"unavailable"
      return
    }
    scopes.value=filesReadScopes(sessions.items,props.projectId)
    limited.value=sessions.items.length===50
    state.value="ready"
  }finally{
    clearTimeout(timeout)
    if(generation===run){controller=null;if(request.signal.aborted){scopes.value=[];state.value="unavailable"}}
  }
}
watch(()=>[props.projectId,props.identity.issuer,props.identity.subject,
  props.identity.client_id,ownerScope.value,props.context.expires_at],()=>{void refresh()},{immediate:true,flush:"sync"})
watch(proofCurrent,yes=>{if(!yes){cancel();state.value="expired"}},{flush:"sync"})
watch(scopesCurrent,yes=>{
  if(!yes&&scopes.value.length){
    // Keep still-current sessions visible: one expiring scope is not
    // evidence that every other session has expired or been revoked.
    scopes.value=retainUnexpiredFilesReadScopes(scopes.value)
    if(!scopes.value.length){cancel();state.value="expired"}
  }
},{flush:"sync"})
onBeforeUnmount(cancel)
</script>
<template>
  <Card class="min-w-0">
    <CardHeader><CardTitle class="text-sm">{{labels.title}}</CardTitle></CardHeader>
    <CardContent class="space-y-3">
      <p v-if="state!=='ready'" role="status" class="text-sm text-muted-foreground">{{state==='loading'?labels.loading:state==='expired'?labels.expired:state==='denied'?labels.denied:labels.unavailable}}</p>
      <p v-else-if="!scopes.length" role="status" class="text-sm text-muted-foreground">{{labels.empty}}</p>
      <div v-else class="max-h-72 space-y-2 overflow-y-auto">
        <div v-for="(row,i) in scopes" :key="row.sessionId+'-'+i" class="min-w-0 rounded-lg border border-border p-3 text-xs">
          <p class="break-all font-mono">{{row.sessionId}}</p>
          <p class="mt-1 break-all font-mono text-muted-foreground">{{labels.selector}}: {{row.selector}}</p>
          <div class="mt-2 flex flex-wrap items-center gap-2">
            <Badge variant="outline">{{labels.revision}} {{row.revision}}</Badge>
            <span class="text-muted-foreground">{{labels.expires}}: {{new Date(row.expiresAt).toLocaleString(locale)}}</span>
          </div>
        </div>
      </div>
      <p v-if="limited" class="text-xs text-muted-foreground">{{labels.limited}}</p>
      <p class="text-xs leading-5 text-muted-foreground">{{labels.boundary}}</p>
      <div class="flex flex-wrap gap-2">
        <Button type="button" variant="outline" size="sm" :disabled="state==='loading'||!proofCurrent" @click="refresh">{{labels.refresh}}</Button>
      </div>
    </CardContent>
  </Card>
</template>
