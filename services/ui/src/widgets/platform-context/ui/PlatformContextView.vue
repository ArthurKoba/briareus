<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue"
import { useI18n } from "vue-i18n"
import {
  readPlatformContext,readProjectContext,
  type PlatformContextState,
  type VerifiedPlatformContext,
} from "@/features/platform/api/platform-current"
import { createSessionOpenRecovery, sessionOpenOwnerKey } from "@/features/agent-sessions"
import type { RauthyPanelIdentity } from "@/features/platform/api/rauthy-oidc"
import ApprovalQueue from "./ApprovalQueue.vue"
import CurrentAgentSessions from "./CurrentAgentSessions.vue"
import OpenNormalSession from "./OpenNormalSession.vue"

/** SOURCE-backed Platform/User proof only. No settings writes, permissions
 * adapter, grant minting or action enablement before BFF owner APIs exist. */
const props=defineProps<{identity:RauthyPanelIdentity}>()
const {locale}=useI18n()
const sessionOpenRecovery=createSessionOpenRecovery()
onBeforeUnmount(()=>sessionOpenRecovery.clear())
const state=ref<PlatformContextState | {kind:"checking"}>({kind:"checking"})
const selected=ref<string|null>(null)
let controller:AbortController|null=null
let deadline:ReturnType<typeof setTimeout>|null=null
let expiryTimer:ReturnType<typeof setTimeout>|null=null
let lastCheckedAt=0

const text=computed(()=>locale.value==="ru"?{
  heading:"Доступ Briareus",
  verifying:"Проверяем текущие Project/Team полномочия…",
  verified:"Platform подтвердил пользователя и области доступа",
  signedOut:"Требуется повторный вход",
  expired:"Сеанс истёк",
  denied:"Пользователь не связан с разрешёнными областями Briareus",
  notCurrent:"Доступ пользователя изменился или больше не действителен",
  invalid:"Сервер вернул некорректное подтверждение прав",
  unavailable:"Сервис участников и полномочий пока недоступен",
  retry:"Повторить проверку",
  teams:"Команды",
  projects:"Проекты",
  unknown:"Нет подтверждённых записей",
  role:"Роль",
  permissions:"Серверные полномочия",
  use:"Доступ к ресурсам",
  approve:"Возможность одобрять AgentSession",
  noRights:"Для этого проекта нет подтверждённых действий",
  details:"Выберите проект для просмотра полученного серверного состояния",
  copyNotice:"Здесь показаны только серверные идентификаторы: имена не получены",
  pending:"Интерфейс approve/deny/revoke ещё не подключён к подтверждённым BFF операциям",
}:{
  heading:"Briareus access",
  verifying:"Checking current Project/Team privileges…",
  verified:"Platform confirmed the user and accessible scopes",
  signedOut:"Sign-in required",
  expired:"Session expired",
  denied:"User is not associated with accessible Briareus scopes",
  notCurrent:"User's access has changed or is no longer current",
  invalid:"Server supplied invalid access evidence",
  unavailable:"Membership and authorization service is currently unavailable",
  retry:"Check again",
  teams:"Teams",
  projects:"Projects",
  unknown:"No verified records",
  role:"Role",
  permissions:"Server-issued permissions",
  use:"Resource access",
  approve:"AgentSession approval eligibility",
  noRights:"No verified actions for this project",
  details:"Select a project to inspect its server-confirmed state",
  copyNotice:"Only server IDs are available; display names were not provided",
  pending:"Approve/deny/revoke controls are not connected to verified Control Panel BFF operations",
})
const proof=computed<VerifiedPlatformContext|null>(()=>state.value.kind==="verified"?state.value.context:null)
const chosen=computed(()=>proof.value?.projects.find(x=>x.id===selected.value)??null)
async function verifyResourceUser(
  signal:AbortSignal,
):Promise<"authorized"|"unauthorized"|"forbidden"|"unavailable">{
  const previous=proof.value,project=chosen.value
  if(!previous||!project||!project.permissions.includes("use_resources"))return "forbidden"
  const fresh=await readProjectContext(props.identity,project.id,signal)
  if(fresh.kind==="expired"||fresh.kind==="signed_out")return "unauthorized"
  if(fresh.kind==="denied"||fresh.kind==="not_current")return "forbidden"
  if(fresh.kind!=="verified")return "unavailable"
  return fresh.context.user.id===previous.user.id
    &&fresh.context.rauthy.subject===props.identity.subject
    &&fresh.context.projects.some(p=>p.id===project.id&&p.permissions.includes("use_resources"))
    ?"authorized":"forbidden"
}
async function verifyApprover(
  signal:AbortSignal,
):Promise<"authorized"|"unauthorized"|"forbidden"|"unavailable">{
  const previous=proof.value, project=chosen.value
  if(!previous||!project||!project.permissions.includes("approve_agent_session"))return "forbidden"
  const fresh=await readProjectContext(props.identity,project.id,signal)
  if(fresh.kind==="expired"||fresh.kind==="signed_out")return "unauthorized"
  if(fresh.kind==="denied"||fresh.kind==="not_current")return "forbidden"
  if(fresh.kind!=="verified")return "unavailable"
  return fresh.context.user.id===previous.user.id
    && fresh.context.rauthy.subject===props.identity.subject
    && fresh.context.projects.some(p=>p.id===project.id&&p.permissions.includes("approve_agent_session"))
    ? "authorized" : "forbidden"
}
const status=computed(()=>{
  switch(state.value.kind){
    case "checking":return text.value.verifying
    case "verified":return text.value.verified
    case "signed_out":return text.value.signedOut
    case "expired":return text.value.expired
    case "denied":return text.value.denied
    case "not_current":return text.value.notCurrent
    case "invalid_response":return text.value.invalid
    case "unavailable":return text.value.unavailable
  }
})
function clear():void {
  controller?.abort();controller=null
  if(deadline!==null){clearTimeout(deadline);deadline=null}
  if(expiryTimer!==null){clearTimeout(expiryTimer);expiryTimer=null}
}
async function refresh():Promise<void>{
  clear()
  const current=new AbortController()
  controller=current
  lastCheckedAt=Date.now()
  state.value={kind:"checking"}
  deadline=setTimeout(()=>current.abort(),8000)
  try {
    const result=await readPlatformContext(props.identity,current.signal)
    if(controller!==current)return
    state.value=current.signal.aborted
      ?{kind:"unavailable",code:"REQUEST_TIMEOUT"}:result
    if(state.value.kind==="verified"){
      const ids=state.value.context.projects.map(x=>x.id)
      if(!selected.value||!ids.includes(selected.value))selected.value=ids[0]??null
      const until=Date.parse(state.value.context.expires_at)-Date.now()
      expiryTimer=setTimeout(()=>{void refresh()},Math.max(1000,Math.min(until,30000)))
    }else selected.value=null
  } finally {
    if(controller===current){controller=null;if(deadline!==null)clearTimeout(deadline);deadline=null}
  }
}
function onVisibility():void {
  if(document.visibilityState==="visible"&&Date.now()-lastCheckedAt>10000)void refresh()
}
watch(()=>props.identity,()=>{void refresh()})
onMounted(()=>{
  void refresh()
  document.addEventListener("visibilitychange",onVisibility)
})
onBeforeUnmount(()=>{
  clear()
  document.removeEventListener("visibilitychange",onVisibility)
})
</script>

<template>
  <section class="mt-5 space-y-3 rounded-xl border border-border bg-card p-4 sm:p-5" aria-labelledby="platform-identity-heading">
    <div class="flex flex-wrap items-center justify-between gap-2">
      <h3 id="platform-identity-heading" class="text-sm font-semibold text-foreground">{{text.heading}}</h3>
      <button type="button" class="min-h-10 rounded-lg border border-border px-3 text-xs font-medium text-foreground hover:bg-muted disabled:opacity-50" :disabled="state.kind==='checking'" @click="refresh">{{text.retry}}</button>
    </div>
    <p :role="state.kind==='invalid_response'?'alert':'status'" class="text-sm text-muted-foreground">{{status}}</p>
    <template v-if="proof">
      <p class="text-xs text-muted-foreground">{{text.role}}: <span class="font-semibold text-foreground">{{proof.user.role}}</span></p>
      <div class="grid gap-3 sm:grid-cols-2">
        <section class="min-w-0 rounded-lg border border-border bg-muted/20 p-3">
          <h4 class="text-xs font-semibold">{{text.teams}} ({{proof.teams.length}})</h4>
          <p v-if="proof.teams.length===0" class="mt-2 text-xs text-muted-foreground">{{text.unknown}}</p>
          <ul v-else class="mt-2 space-y-2">
            <li v-for="team in proof.teams" :key="team.id" class="break-all font-mono text-xs text-foreground">{{team.id}}</li>
          </ul>
        </section>
        <section class="min-w-0 rounded-lg border border-border bg-muted/20 p-3">
          <h4 class="text-xs font-semibold">{{text.projects}} ({{proof.projects.length}})</h4>
          <p v-if="proof.projects.length===0" class="mt-2 text-xs text-muted-foreground">{{text.unknown}}</p>
          <div v-else class="mt-2 flex flex-wrap gap-2">
            <button v-for="project in proof.projects" :key="project.id" type="button"
              class="min-h-10 rounded-lg border border-border px-3 text-left font-mono text-xs focus-visible:outline-2 focus-visible:outline-ring"
              :class="selected===project.id?'bg-primary text-primary-foreground':'hover:bg-muted'"
              :aria-pressed="selected===project.id" @click="selected=project.id">{{project.id.slice(0,8)}}…</button>
          </div>
        </section>
      </div>
      <div v-if="chosen" class="space-y-2 rounded-lg border border-border bg-muted/20 p-3">
        <p class="break-all font-mono text-xs">{{chosen.id}}</p>
        <p class="text-xs font-semibold">{{text.permissions}}</p>
        <ul v-if="chosen.permissions.length" class="list-inside list-disc space-y-1 text-xs">
          <li v-for="permission in chosen.permissions" :key="permission">{{permission==='use_resources'?text.use:text.approve}}</li>
        </ul>
        <p v-else class="text-xs text-muted-foreground">{{text.noRights}}</p>
      </div>
      <OpenNormalSession v-if="chosen && chosen.permissions.includes('use_resources')"
        :project-id="chosen.id" :actor-id="proof.user.id" :proof-expires-at="proof.expires_at"
        :can-open="true" :can-approve="chosen.permissions.includes('approve_agent_session')" :verify-user="verifyResourceUser" :recovery="sessionOpenRecovery"
        :owner-key="sessionOpenOwnerKey(identity.issuer,identity.subject,identity.client_id,proof.user.id)"/>
      <template v-if="chosen && chosen.permissions.some(right=>right==='use_resources'||right==='approve_agent_session')">
        <CurrentAgentSessions :key="'sessions-'+chosen.id"
          :project-id="chosen.id" :actor-id="proof.user.id" :proof-expires-at="proof.expires_at"
          :can-list="true" :can-approve="chosen.permissions.includes('approve_agent_session')"
          :verify-approver="verifyApprover"/>
        <ApprovalQueue :key="'approvals-'+chosen.id"
          :project-id="chosen.id" :actor-id="proof.user.id" :proof-expires-at="proof.expires_at"
          :can-read="true" :can-approve="chosen.permissions.includes('approve_agent_session')"
          :verify-approver="verifyApprover"/>
      </template>
      <p class="text-xs text-muted-foreground">{{text.copyNotice}}</p>
      <p class="text-xs text-muted-foreground">{{text.pending}}</p>
    </template>
  </section>
</template>
