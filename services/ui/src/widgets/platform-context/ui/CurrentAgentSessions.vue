<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue"
import { useI18n } from "vue-i18n"
import { AlertCircle, Clock, RefreshCw } from "lucide-vue-next"
import {
  listCurrentSessions, isCurrentSessionId, revokeVerifiedSession, SessionInspector, pruneElapsedSessionRows, type CurrentAgentSession,
} from "@/features/agent-sessions"
import { useProofLifetime } from "@/shared/lib/use-proof-lifetime"
import { Badge } from "@/shared/ui/badge"
import { Button } from "@/shared/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/shared/ui/card"
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from "@/shared/ui/dialog"
import { Input } from "@/shared/ui/input"
import { Skeleton } from "@/shared/ui/skeleton"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/shared/ui/table"

type LoadState="idle"|"loading"|"ready"|"unauthorized"|"denied"|"invalid"|"unavailable"|"stale"
type Fresh="authorized"|"unauthorized"|"forbidden"|"unavailable"
const props=withDefaults(defineProps<{
  projectId?:string
  actorId?:string
  proofExpiresAt?:string
  canList?:boolean
  canApprove?:boolean
  verifyApprover?:(signal:AbortSignal)=>Promise<Fresh>
  designPreview?:boolean
  previewState?:"empty"|"loading"|"denied"|"unavailable"
}>(),{designPreview:false,previewState:"empty"})

const {locale}=useI18n()
const msg=computed(()=>locale.value==="ru"?{
  heading:"Текущие AgentSession",
  source:"Серверные сеансы выбранного проекта, текущая ревизия и операции",
  all:"Все",active:"Активные",revoked:"Отозваны",expired:"Истекли",
  id:"Сеанс",operations:"Операции",status:"Состояние",
  revision:"Ревизия",scope:"Ресурсы",expires:"Срок",actions:"Действия",
  actor:"Инициатор",elevated:"Расширенный",normal:"Обычный",
  inspect:"Подробнее",detail:"Текущий AgentSession",detailSource:"Отдельное серверное чтение выбранного сеанса",
  lookup:"Открыть сеанс по ID",lookupLabel:"ID AgentSession",lookupHint:"Точное чтение в выбранном проекте, включая сеансы вне загруженного списка.",
  lookupInvalid:"Введите канонический UUIDv4 сеанса",recoverTarget:"Проверить исходный сеанс",
  observed:"Ответ команды потерян. Показано текущее состояние сеанса по отдельному чтению, а не подтверждение выполнения этой команды.",
  proofExpired:"Подтверждение доступа к проекту истекло",
  refresh:"Обновить",search:"Поиск по ID, инициатору и операции",
  empty:"Подтверждённых сеансов пока нет",noMatch:"В загруженном списке нет сеансов по выбранным фильтрам",clearFilter:"Сбросить фильтры",
  stale:"Срок активного сеанса в снимке истёк. Обновите список для текущего состояния.",
  loading:"Получаем текущие сеансы и ревизии…",
  idle:"Для просмотра нужен действующий серверный доступ к проекту",
  unauthorized:"Сеанс входа завершён; требуется повторная авторизация",
  denied:"Сервер не подтвердил доступ к сеансам проекта",
  invalid:"Некорректное подтверждение сеансов от Backend",
  unavailable:"История сеансов временно недоступна; никаких действий выполнять нельзя",
  revoke:"Отозвать",review:"Проверить отзыв сеанса",
  confirm:"Подтвердить отзыв",cancel:"Отмена",
  warning:"Отзыв требует действующего полномочия approver и текущей ревизии гранта. Действие нельзя отменить.",
  uncertainty:"Сервер не подтвердил окончательный результат отзыва. Перед повторной операцией обновите список.",
  conflict:"Ревизия сеанса изменилась. Список обновлён; проверьте состояние.",
  failure:"Отзыв запрещён или не подтверждён сервером.",
  success:"Отзыв подтверждён повторным чтением состояния сервера.",
  elevationBlocked:"Повышение полномочий требует выбранных серверно подтверждённых ресурсов и операции; произвольные scope не отправляются.",
}:{
  heading:"Current AgentSessions",
  source:"Server-owned Project sessions, current revisions and operations",
  all:"All",active:"Active",revoked:"Revoked",expired:"Expired",
  id:"Session",operations:"Operations",status:"Status",
  revision:"Revision",scope:"Resources",expires:"Expiry",actions:"Actions",
  actor:"Created by",elevated:"Elevated",normal:"Normal",
  inspect:"Details",detail:"Current AgentSession",detailSource:"Independent server read of the selected session",
  lookup:"Open session by ID",lookupLabel:"AgentSession ID",lookupHint:"Exact read within the selected Project, including sessions outside the loaded list.",
  lookupInvalid:"Enter a canonical session UUIDv4",recoverTarget:"Inspect original session",
  observed:"Command reply was lost. The separate read shows current session state, not proof that this command completed.",
  proofExpired:"Project access proof expired",
  refresh:"Refresh",search:"Find by ID, actor or operation",
  empty:"No server-confirmed sessions",noMatch:"No loaded sessions match these filters",clearFilter:"Clear filters",
  stale:"An active session in this snapshot expired. Refresh the list for current state.",
  loading:"Loading current sessions and grant revisions…",
  idle:"Current Project access required to view sessions",
  unauthorized:"Login session ended; sign in again",
  denied:"Server did not verify access to Project sessions",
  invalid:"Backend returned invalid session evidence",
  unavailable:"Session inventory unavailable; actions are disabled",
  revoke:"Revoke",review:"Review session revocation",
  confirm:"Confirm revoke",cancel:"Cancel",
  warning:"Revocation requires current approver permission and grant revision. This action cannot be undone.",
  uncertainty:"Server did not verify revocation outcome. Refresh before attempting another operation.",
  conflict:"Session revision changed. List refreshed; review current state.",
  failure:"Revocation was denied or unconfirmed by the server.",
  success:"Revocation confirmed by reading the exact current session.",
  elevationBlocked:"Elevation requires verified resource selectors and effects; arbitrary scopes are never sent.",
})
const status=ref<LoadState>("idle")
const items=ref<CurrentAgentSession[]>([])
const filtering=ref<"all"|"active"|"revoked"|"expired">("all")
const search=ref("")
const busy=ref(false)
const refreshing=ref(false)
const error=ref("")
const info=ref("")
const confirmation=ref<CurrentAgentSession|null>(null)
const inspecting=ref<string|null>(null)
const lookupId=ref("")
const lastTarget=ref<string|null>(null)
const proofCurrent=useProofLifetime(()=>props.proofExpiresAt)
const snapshotExpiry=computed(()=>{
  const active=items.value.filter(row=>row.status==="active")
  return active.length?new Date(Math.min(...active.map(row=>Date.parse(row.hard_expires_at)))).toISOString():null
})
const snapshotCurrent=useProofLifetime(()=>snapshotExpiry.value)
let generation=0
let controller:AbortController|null=null
let timeout:ReturnType<typeof setTimeout>|null=null

const canFetch=computed(()=>props.canList===true&&typeof props.projectId==="string"
  &&typeof props.actorId==="string"&&typeof props.proofExpiresAt==="string"
  &&proofCurrent.value&&Date.parse(props.proofExpiresAt)>Date.now())
const shown=computed(()=>items.value.filter(item=>
  (filtering.value==="all"||item.status===filtering.value)&&
  (search.value.trim()===""||[
    item.session_uuid,item.created_by_user_uuid,...item.operations,
  ].some(value=>value.toLocaleLowerCase().includes(search.value.trim().toLocaleLowerCase())))
))
const currentStatus=computed<LoadState>(()=>props.designPreview?
  props.previewState==="empty"?"ready":props.previewState==="loading"?"loading":
    props.previewState==="denied"?"denied":"unavailable":status.value)
const statusText=computed(()=>currentStatus.value==="ready"?(items.value.length?msg.value.noMatch:msg.value.empty):msg.value[currentStatus.value])
function cancel():void{
  ++generation
  controller?.abort()
  controller=null
  if(timeout!==null){clearTimeout(timeout);timeout=null}
}
function reset():void {
  cancel()
  items.value=[]
  status.value="idle"
  error.value=""
  info.value=""
  busy.value=false
  refreshing.value=false
  confirmation.value=null
  inspecting.value=null
  lookupId.value="";lastTarget.value=null
}
function actionAllowed(item:CurrentAgentSession):boolean {
  const current=items.value.find(row=>row.session_uuid===item.session_uuid)
  return !!current&&current.project_uuid===props.projectId&&current.revision===item.revision&&
    current.created_by_user_uuid===item.created_by_user_uuid&&
    current.status==="active"&&current.allowed_actions.includes("revoke")&& !props.designPreview&&status.value==="ready"&&
    !busy.value&&!refreshing.value&&canFetch.value&&props.canApprove===true&&
    typeof props.verifyApprover==="function"&&item.status==="active"&&
    Date.parse(item.hard_expires_at)>Date.now()&&item.allowed_actions.includes("revoke")
}
async function refresh():Promise<void> {
  if(busy.value)return
  if(props.designPreview||!props.projectId||!props.actorId||!canFetch.value){reset();return}
  cancel()
  const request=new AbortController(),gen=++generation
  controller=request
  refreshing.value=true
  error.value=""
  info.value=""
  if(status.value!=="ready")status.value="loading"
  const deadline=setTimeout(()=>request.abort(),8000)
  timeout=deadline
  try{
    const result=await listCurrentSessions(props.projectId,props.actorId,props.canApprove===true,request.signal)
    if(gen!==generation||request.signal.aborted)return
    if(result.kind==="ready"){
      items.value=result.items;status.value="ready"
      const pending=confirmation.value
      if(pending&&!result.items.some(row=>row.session_uuid===pending.session_uuid&&
        row.revision===pending.revision&&row.status==="active"&&row.allowed_actions.includes("revoke"))){
        confirmation.value=null;error.value=msg.value.conflict
      }
    }else{
      confirmation.value=null
      items.value=[]
      status.value=result.kind==="unauthorized"?"unauthorized":
        result.kind==="forbidden"?"denied":
        result.kind==="invalid"?"invalid":"unavailable"
    }
  }finally{
    clearTimeout(deadline)
    if(gen===generation){
      if(request.signal.aborted){confirmation.value=null;items.value=[];status.value="unavailable"}
      timeout=null;controller=null;refreshing.value=false
    }
  }
}
function lookup():void {
  const id=lookupId.value.trim()
  if(!props.designPreview&&canFetch.value&&!busy.value&&!refreshing.value&&isCurrentSessionId(id))inspecting.value=id
}
function requestRevoke(item:CurrentAgentSession):void {
  if(!actionAllowed(item))return
  confirmation.value=item
}
async function confirmRevoke():Promise<void> {
  const original=confirmation.value
  if(!original||!actionAllowed(original)||!props.projectId||!props.actorId||!props.verifyApprover)return
  cancel()
  const request=new AbortController(),gen=++generation
  controller=request;busy.value=true;error.value="";info.value=""
  lastTarget.value=original.session_uuid
  const deadline=setTimeout(()=>request.abort(),9000)
  timeout=deadline
  try{
    const result=await revokeVerifiedSession(original,{
      signal:request.signal,verify:props.verifyApprover,
      context:()=>gen===generation&&props.projectId&&props.actorId&&props.canList===true?{
        projectId:props.projectId,actorId:props.actorId,canApprove:props.canApprove===true,
        proofExpiresAt:props.proofExpiresAt??"",
      }:null,
    })
    if(gen!==generation)return
    confirmation.value=null
    if(result.kind==="confirmed"||result.kind==="conflict"||result.kind==="observed"){
      items.value=items.value.map(row=>row.session_uuid===result.item.session_uuid?result.item:row)
      status.value="ready"
      if(result.kind==="confirmed"){info.value=msg.value.success;lastTarget.value=null}
      else if(result.kind==="observed")info.value=msg.value.observed
      else error.value=msg.value.conflict
    }else{
      // Do not leave actionable stale rows after an ambiguous or denied command.
      items.value=[];status.value="unavailable"
      error.value=result.kind==="uncertain"?msg.value.uncertainty:
        result.kind==="unauthorized"?msg.value.unauthorized:
        result.kind==="forbidden"?msg.value.denied:
        result.kind==="invalid"?msg.value.invalid:msg.value.unavailable
    }
  }finally{
    clearTimeout(deadline)
    if(gen===generation){controller=null;timeout=null;busy.value=false}
  }
}
watch(()=>[props.projectId,props.actorId,props.canList,props.canApprove,props.designPreview],()=>{
  reset();void refresh()
},{flush:"sync"})
watch(()=>props.proofExpiresAt,value=>{
  if(!value||!(Date.parse(value)>Date.now())){reset();return}
  if(!busy.value)void refresh()
})
watch(proofCurrent,current=>{if(!current){reset();status.value="denied";error.value=msg.value.proofExpired}},{flush:"sync"})
watch([snapshotCurrent,busy,status],()=>{
  if(!busy.value&&status.value==="ready"&&snapshotExpiry.value&&!snapshotCurrent.value){
    // useProofLifetime is monotonic: the clock can move backwards after an
    // expiry. At least the fired earliest deadline must remain irreversible.
    const cutoff=Math.max(Date.now(),Date.parse(snapshotExpiry.value))
    const aged=pruneElapsedSessionRows(items.value,cutoff)
    cancel()
    items.value=aged.items
    if(confirmation.value&&!aged.items.some(row=>
      row.session_uuid===confirmation.value?.session_uuid&&
      row.revision===confirmation.value?.revision&&row.status==="active")){
      confirmation.value=null
    }
    refreshing.value=false;error.value=""
    // Other sessions are still valid *snapshots*, not fresh Cedar permits.
    // Do not duplicate the stale banner when no rows remain.
    info.value=aged.items.length?msg.value.stale:""
    status.value=aged.items.length?"ready":"stale"
  }
},{flush:"sync"})
onMounted(()=>{void refresh()})
onBeforeUnmount(reset)
</script>

<template>
  <Card class="min-w-0">
    <CardHeader class="flex flex-row flex-wrap items-start justify-between gap-3">
      <div class="space-y-1">
        <CardTitle class="text-sm">{{msg.heading}}</CardTitle>
        <p class="text-xs leading-5 text-muted-foreground">{{msg.source}}</p>
      </div>
      <Button variant="outline" size="sm" :disabled="designPreview||!canFetch||busy||refreshing" @click="refresh">
        <RefreshCw class="mr-1 size-4" :class="refreshing?'animate-spin':''" aria-hidden="true"/>{{msg.refresh}}
      </Button>
    </CardHeader>
    <CardContent class="min-w-0 space-y-4">
      <form class="space-y-2" @submit.prevent="lookup">
        <label class="block text-xs font-medium"><span>{{msg.lookupLabel}}</span>
          <Input v-model="lookupId" class="mt-2" maxlength="64" autocomplete="off" :disabled="!canFetch||busy"/>
        </label>
        <p class="text-xs text-muted-foreground">{{msg.lookupHint}}</p>
        <p v-if="lookupId&&!isCurrentSessionId(lookupId.trim())" class="text-xs text-muted-foreground" role="status">{{msg.lookupInvalid}}</p>
        <Button type="submit" variant="outline" size="sm" :disabled="designPreview||!canFetch||busy||refreshing||!isCurrentSessionId(lookupId.trim())">{{msg.lookup}}</Button>
        <Button v-if="lastTarget" type="button" variant="outline" size="sm" :disabled="!canFetch||busy||refreshing" @click="inspecting=lastTarget">{{msg.recoverTarget}}</Button>
      </form>

      <div class="flex flex-wrap gap-2" role="group" :aria-label="msg.status">
        <Button v-for="filter in (['all','active','revoked','expired'] as const)" :key="filter"
          type="button" size="sm" :variant="filtering===filter?'default':'outline'"
          :aria-pressed="filtering===filter" @click="filtering=filter">{{msg[filter]}}</Button>
        <Input v-model="search" class="w-full sm:ml-auto sm:w-64" :placeholder="msg.search"
          :aria-label="msg.search" maxlength="128"/>
        <Button v-if="search||filtering!=='all'" variant="ghost" size="sm" @click="search='';filtering='all'">{{msg.clearFilter}}</Button>
      </div>
      <p v-if="error" role="alert" class="flex items-start gap-2 rounded-lg border border-destructive/20 bg-destructive/5 p-3 text-sm text-destructive">
        <AlertCircle class="mt-0.5 size-4 shrink-0" aria-hidden="true"/>{{error}}
      </p>
      <p v-if="info" role="status" class="rounded-lg border border-border bg-muted/20 p-3 text-sm">{{info}}</p>
      <div v-if="currentStatus==='loading'" class="space-y-3" role="status">
        <Skeleton v-for="i in 3" :key="i" class="h-11 w-full"/>
      </div>
      <p v-else-if="currentStatus!=='ready'||!shown.length" role="status"
        class="rounded-xl border border-dashed border-border px-4 py-10 text-center text-sm text-muted-foreground">{{statusText}}</p>
      <div v-else class="min-w-0 overflow-x-auto rounded-xl border border-border">
        <Table class="min-w-[650px] text-sm">
          <TableHeader>
            <TableRow>
              <TableHead>{{msg.id}}</TableHead>
              <TableHead>{{msg.actor}}</TableHead>
              <TableHead>{{msg.operations}}</TableHead>
              <TableHead>{{msg.status}} / {{msg.revision}}</TableHead>
              <TableHead>{{msg.actions}}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            <TableRow v-for="session in shown" :key="session.session_uuid">
              <TableCell class="max-w-32 break-all font-mono text-[11px]">{{session.session_uuid}}</TableCell>
              <TableCell class="max-w-32 break-all font-mono text-[11px]">{{session.created_by_user_uuid}}</TableCell>
              <TableCell class="min-w-32 max-w-60 text-xs">
                <p v-for="operation in session.operations" :key="operation">{{operation}}</p>
                <details v-if="session.resources.length" class="mt-2 text-muted-foreground">
                  <summary class="cursor-pointer">{{msg.scope}}: {{session.resources.length}}</summary>
                  <p v-for="(scope,i) in session.resources" :key="i" class="mt-1 break-all font-mono text-[11px]">
                    {{scope.hand}} · {{scope.tool}} · {{scope.resource.kind}}: {{scope.resource.id}}
                  </p>
                </details>
              </TableCell>
              <TableCell class="min-w-32 text-xs">
                <Badge variant="outline">{{msg[session.status]}}</Badge>
                <p class="mt-2">v{{session.revision}} · {{session.is_elevated?msg.elevated:msg.normal}}</p>
                <p class="mt-1 flex items-center gap-1 text-muted-foreground">
                  <Clock class="size-3" aria-hidden="true"/>{{new Date(session.hard_expires_at).toLocaleString(locale)}}
                </p>
              </TableCell>
              <TableCell class="space-y-1">
                <Button variant="outline" size="sm" :disabled="busy||refreshing||!canFetch" @click="inspecting=session.session_uuid">{{msg.inspect}}</Button>
                <Button v-if="actionAllowed(session)" variant="outline" size="sm"
                  @click="requestRevoke(session)">{{msg.revoke}}</Button>
              </TableCell>
            </TableRow>
          </TableBody>
        </Table>
      </div>
      <p class="text-xs leading-5 text-muted-foreground">{{msg.elevationBlocked}}</p>
    </CardContent>
  </Card>
  <Dialog :open="inspecting!==null" @update:open="open=>{if(!open)inspecting=null}">
    <DialogContent class="max-h-[85vh] overflow-y-auto">
      <DialogHeader><DialogTitle>{{msg.detail}}</DialogTitle><DialogDescription>{{msg.detailSource}}</DialogDescription></DialogHeader>
      <SessionInspector v-if="inspecting&&projectId&&actorId&&proofExpiresAt" :key="inspecting"
        :project-id="projectId" :session-id="inspecting" :actor-id="actorId" :proof-expires-at="proofExpiresAt"
        :can-list="canList===true" :can-approve="canApprove===true"/>
    </DialogContent>
  </Dialog>
  <Dialog :open="confirmation!==null" @update:open="open=>{if(!open&&!busy)confirmation=null}">
    <DialogContent>
      <DialogHeader>
        <DialogTitle>{{msg.review}}</DialogTitle>
        <DialogDescription>{{msg.warning}}</DialogDescription>
      </DialogHeader>
      <div v-if="confirmation" class="space-y-2 text-sm">
        <p class="break-all font-mono text-xs">{{confirmation.session_uuid}}</p>
        <p>{{msg.revision}}: {{confirmation.revision}}</p>
        <p>{{msg.operations}}: {{confirmation.operations.join(", ")}}</p>
      </div>
      <DialogFooter>
        <Button variant="outline" :disabled="busy" @click="confirmation=null">{{msg.cancel}}</Button>
        <Button :disabled="!confirmation||!actionAllowed(confirmation)" @click="confirmRevoke">{{msg.confirm}}</Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>
</template>
