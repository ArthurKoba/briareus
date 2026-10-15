<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue"
import { useI18n } from "vue-i18n"
import { AlertCircle, CheckCircle2, Clock, RefreshCw, ShieldCheck } from "lucide-vue-next"
import { readProjectApprovals, resolveCurrentApproval, approvalStillCurrentForActor } from "@/features/approvals"
import { useProofLifetime } from "@/shared/lib/use-proof-lifetime"
import { SessionInspector } from "@/features/agent-sessions"
import type { ApprovalAction, ApprovalRecord } from "@/features/approvals/types"
import { Badge } from "@/shared/ui/badge"
import { Button } from "@/shared/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/shared/ui/card"
import { Input } from "@/shared/ui/input"
import { Skeleton } from "@/shared/ui/skeleton"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/shared/ui/table"
import {
  Dialog, DialogContent, DialogDescription, DialogFooter,
  DialogHeader, DialogTitle,
} from "@/shared/ui/dialog"

type LoadState = "idle"|"loading"|"ready"|"denied"|"expired"|"unavailable"|"invalid"|"stale"
const props=withDefaults(defineProps<{
  projectId?:string
  actorId?:string
  proofExpiresAt?:string
  canRead?:boolean
  canApprove?:boolean
  verifyApprover?: (signal:AbortSignal)=>Promise<"authorized"|"unauthorized"|"forbidden"|"unavailable">
  designPreview?:boolean
  previewState?:"empty"|"loading"|"denied"|"unavailable"
}>(),{designPreview:false,previewState:"empty"})
const {locale}=useI18n()
const labels=computed(()=>locale.value==="ru"?{
  title:"Запросы AgentSession",source:"Проверенные записи выбранного проекта",
  unavailable:"Источник согласований недоступен. Решения не выполняются.",
  invalid:"Сервер вернул некорректный список согласований.",
  denied:"Сервер отказал в доступе к согласованиям.",
  expired:"Сеанс истёк. Необходимо войти повторно.",
  snapshotStale:"Срок ожидающей заявки в снимке истёк. Обновите список перед решением.",
  loading:"Проверяем текущие согласования…",
  empty:"Нет подтверждённых запросов",
  all:"Все",pending:"Ожидают",approved:"Одобрены",rejected:"Отклонены",
  search:"Поиск по идентификатору или операции",refresh:"Обновить",
  requester:"Инициатор",session:"AgentSession",operations:"Операции",
  resource:"Ресурсы и инструменты",expires:"Срок запроса",status:"Состояние",
  actions:"Действия",approve:"Одобрить",deny:"Отклонить",
  inspectIssued:"Выданный сеанс",issuedTitle:"Текущее состояние выданного сеанса",issuedNote:"Результат согласования не заменяет текущую ревизию и состояние AgentSession.",
  inspectRequest:"Данные заявки",requestId:"Заявка",version:"Ревизия",resolver:"Решение принял",issuedId:"Выданная AgentSession",
  detailNote:"Просмотр текущей заявки без изменения её состояния. Решение и выдача прав выполняются отдельно.",
  noMatch:"В загруженном списке нет заявок по выбранным фильтрам",clearFilter:"Сбросить фильтры",
  limited:"Показаны не более 50 заявок. Отсутствие заявки в этой выборке не подтверждает её удаление.",
  details:"Проверить заявку",confirm:"Подтвердить решение",cancel:"Отмена",
  stale:"Запрос изменился; требуется обновить список.",
  observed:"Ответ команды согласования потерян. Показано текущее состояние заявки, а не подтверждение выполнения этой команды.",
  uncertain:"Результат операции не подтверждён. Перед повторным действием обновите список.",
  failed:"Сервер не подтвердил операцию.",
  readOnly:"Управление включается только после проверки роли и разрешения самим сервером.",
  noSessions:"Создание, отзыв и текущие ревизии находятся в отдельном списке AgentSession; запрос повышения требует точного выбранного ресурса.",
}:{
  title:"AgentSession approvals",source:"Server-verified records for the selected project",
  unavailable:"Approval authority unavailable. No decisions are executed.",
  invalid:"Server returned an invalid approval list.",
  denied:"Server denied access to approval requests.",
  expired:"Session expired. Sign in again.",
  snapshotStale:"A pending request in this snapshot expired. Refresh before deciding.",
  loading:"Checking current approval requests…",
  empty:"No verified requests",
  all:"All",pending:"Pending",approved:"Approved",rejected:"Rejected",
  search:"Find by ID or operation",refresh:"Refresh",
  requester:"Requester",session:"AgentSession",operations:"Operations",
  resource:"Resources and tools",expires:"Request expiry",status:"Status",
  actions:"Actions",approve:"Approve",deny:"Deny",
  inspectIssued:"Issued session",issuedTitle:"Current issued-session state",issuedNote:"An approval receipt does not replace the current AgentSession status and revision.",
  inspectRequest:"Request details",requestId:"Request",version:"Revision",resolver:"Resolved by",issuedId:"Issued AgentSession",
  detailNote:"Read the current request without changing it. Decisions and grants are separate operations.",
  noMatch:"No loaded requests match these filters",clearFilter:"Clear filters",
  limited:"At most 50 requests are shown. Absence from this selection does not confirm deletion.",
  details:"Review request",confirm:"Confirm decision",cancel:"Cancel",
  stale:"Request changed; refresh the list.",
  observed:"Approval command reply was lost. The latest read shows current request state, not proof that this command completed.",
  uncertain:"Operation outcome is unconfirmed. Refresh before retrying.",
  failed:"Server did not confirm the operation.",
  readOnly:"Actions require fresh server proof of approver rights.",
  noSessions:"Normal creation, revocation and grant revisions are shown in the AgentSession list. Elevation requests require exact authorized resource selection.",
})
const issued=ref<string|null>(null)
const filter=ref<"all"|"pending"|"approved"|"rejected">("all")
const query=ref("")
const records=ref<ApprovalRecord[]>([])
const reviewedId=ref<string|null>(null)
const reviewed=computed(()=>state.value==="ready"?records.value.find(row=>row.id===reviewedId.value)??null:null)
const state=ref<LoadState>("idle")
const refreshing=ref(false)
const mutating=ref(false)
const error=ref("")
const observation=ref("")
const confirmation=ref<{item:ApprovalRecord;action:ApprovalAction}|null>(null)
let controller:AbortController|null=null
let generation=0
const proofCurrent=useProofLifetime(()=>props.proofExpiresAt)
const snapshotExpiry=computed(()=>{
  const pending=records.value.filter(row=>row.status==="pending"&&row.allowed_actions.length>0)
  return pending.length?new Date(Math.min(...pending.map(row=>Date.parse(row.requested_expires_at)))).toISOString():null
})
const snapshotCurrent=useProofLifetime(()=>snapshotExpiry.value)
const canRead=computed(()=>props.canRead===true&&typeof props.actorId==="string"
  &&typeof props.projectId==="string"
  &&typeof props.proofExpiresAt==="string"
  &&proofCurrent.value&&Date.parse(props.proofExpiresAt)>Date.now())
const approver=computed(()=>props.canApprove===true&&typeof props.verifyApprover==="function")
const shown=computed(()=>records.value.filter(row=>
  (filter.value==="all"||row.status===filter.value)
  && (query.value.trim()===""||
    [row.id,row.agent_session_uuid,row.requested_by_user_uuid,...row.requested_operations]
      .some(x=>x.toLowerCase().includes(query.value.toLowerCase().trim())))
))
const displayState=computed<LoadState>(()=>props.designPreview
  ?props.previewState==="empty"?"ready":props.previewState==="loading"?"loading":
    props.previewState==="denied"?"denied":"unavailable"
  :state.value)
const stateMessage=computed(()=>{
  switch(displayState.value){
    case "idle":return labels.value.readOnly
    case "loading":return labels.value.loading
    case "ready":return labels.value.empty
    case "denied":return labels.value.denied
    case "expired":return labels.value.expired
    case "invalid":return labels.value.invalid
    case "unavailable":return labels.value.unavailable
    case "stale":return labels.value.snapshotStale
  }
})
function reset():void{
  ++generation
  controller?.abort()
  controller=null
  records.value=[]
  state.value="idle"
  confirmation.value=null
  issued.value=null;reviewedId.value=null
  error.value="";observation.value=""
  refreshing.value=false
  mutating.value=false
}
async function refresh():Promise<void>{
  if(mutating.value)return
  if(props.designPreview||!props.projectId||!canRead.value){reset();return}
  controller?.abort()
  const current=new AbortController(),gen=++generation
  controller=current
  records.value=[]
  refreshing.value=true
  error.value="";observation.value=""
  state.value="loading"
  const timer=setTimeout(()=>current.abort(),8000)
  try{
    const result=await readProjectApprovals(props.projectId,current.signal)
    if(gen!==generation||current.signal.aborted)return
    if(result.kind==="ready"){
      if(props.canApprove!==true&&result.items.some(row=>row.requested_by_user_uuid!==props.actorId||row.allowed_actions.length!==0)){
        confirmation.value=null;issued.value=null;reviewedId.value=null;records.value=[];state.value="invalid";return
      }
      records.value=result.items;state.value="ready"
      if(reviewedId.value&&!result.items.some(row=>row.id===reviewedId.value))reviewedId.value=null
      if(issued.value&&!result.items.some(row=>row.status==="approved"&&row.issued_session_uuid===issued.value))issued.value=null
      const pending=confirmation.value
      if(pending&&!stillCurrentAction(pending.item,pending.action)){
        confirmation.value=null;error.value=labels.value.stale
      }
    }else{
      confirmation.value=null;issued.value=null;reviewedId.value=null
      records.value=[]
      state.value=result.kind==="unauthorized"?"expired":
        result.kind==="forbidden"?"denied":result.kind==="invalid"?"invalid":"unavailable"
    }
  }finally{
    clearTimeout(timer)
    if(gen===generation){
      if(current.signal.aborted){confirmation.value=null;issued.value=null;reviewedId.value=null;records.value=[];state.value="unavailable"}
      refreshing.value=false
      controller=null
    }
  }
}
const canChoose=computed(()=>!props.designPreview&&state.value==="ready"&&!refreshing.value&&!mutating.value&&canRead.value&&approver.value)
function stillCurrentAction(row:ApprovalRecord,action:ApprovalAction):boolean{
  return !!props.projectId&&!!props.actorId&&approvalStillCurrentForActor(
    row,records.value,action,props.projectId,props.actorId,
  )
}
function allowAction(row:ApprovalRecord,action:ApprovalAction):boolean{
  return canChoose.value&&stillCurrentAction(row,action)
}
function requestAction(row:ApprovalRecord,action:ApprovalAction):void{
  if(!allowAction(row,action))return
  confirmation.value={item:row,action}
}
async function confirmAction():Promise<void>{
  const pending=confirmation.value
  if(!pending||mutating.value||!props.verifyApprover||!props.projectId||!props.actorId||
    !allowAction(pending.item,pending.action))return
  mutating.value=true
  error.value="";observation.value=""
  const current=new AbortController(),gen=++generation
  controller?.abort()
  controller=current
  const timer=setTimeout(()=>current.abort(),9000)
  try{
    const result=await resolveCurrentApproval(pending.item,pending.action,{
      signal:current.signal,verify:props.verifyApprover,
      context:()=>gen===generation&&props.projectId&&props.actorId&&props.canRead===true?{
        projectId:props.projectId,actorId:props.actorId,
        proofExpiresAt:props.proofExpiresAt??"",canApprove:props.canApprove===true,
        rows:records.value,
      }:null,
    })
    if(gen!==generation)return
    confirmation.value=null
    if(result.kind==="confirmed"||result.kind==="conflict"||result.kind==="observed"){
      records.value=result.items;state.value="ready"
      if(result.kind==="conflict")error.value=labels.value.stale
      if(result.kind==="observed")observation.value=labels.value.observed
    }else{
      // A failed/ambiguous POST must not leave stale actionable rows behind.
      records.value=[];state.value="unavailable"
      error.value=result.kind==="unauthorized"?labels.value.expired:
        result.kind==="forbidden"?labels.value.denied:
        result.kind==="invalid"?labels.value.invalid:
        result.kind==="uncertain"?labels.value.uncertain:labels.value.unavailable
    }
  }finally{
    clearTimeout(timer)
    if(gen===generation){controller=null;mutating.value=false}
  }
}
watch(()=>[props.projectId,props.actorId,props.canRead,props.canApprove,props.designPreview],()=>{
  reset();void refresh()
},{flush:"sync"})
watch(()=>props.proofExpiresAt,value=>{
  if(!value||!(Date.parse(value)>Date.now())){reset();state.value="expired";return}
  if(!mutating.value)void refresh()
})
watch(proofCurrent,current=>{if(!current){reset();state.value="expired"}},{flush:"sync"})
watch([snapshotCurrent,mutating,state],()=>{
  if(!mutating.value&&state.value==="ready"&&snapshotExpiry.value&&!snapshotCurrent.value){
    reset();state.value="stale"
  }
},{flush:"sync"})
onMounted(()=>{void refresh()})
onBeforeUnmount(reset)
</script>
<template>
  <Card class="min-w-0">
    <CardHeader class="flex flex-row flex-wrap items-start justify-between gap-3">
      <div class="space-y-1">
        <CardTitle class="flex items-center gap-2 text-sm"><ShieldCheck class="size-4"/>{{labels.title}}</CardTitle>
        <p class="text-xs text-muted-foreground">{{labels.source}}</p>
      </div>
      <Button variant="outline" size="sm" :disabled="designPreview||!canRead||refreshing||mutating" @click="refresh">
        <RefreshCw class="mr-1 size-4" :class="refreshing?'animate-spin':''" />{{labels.refresh}}
      </Button>
    </CardHeader>
    <CardContent class="space-y-4">
      <div class="flex flex-wrap items-center gap-2" :aria-label="labels.status" role="group">
        <Button v-for="key in (['all','pending','approved','rejected'] as const)" :key="key" size="sm"
          :variant="filter===key?'default':'outline'" :aria-pressed="filter===key" @click="filter=key">{{labels[key]}}</Button>
        <Input v-model="query" class="w-full sm:ml-auto sm:w-60" maxlength="128" :placeholder="labels.search" :aria-label="labels.search"/>
        <Button v-if="query||filter!=='all'" variant="ghost" size="sm" @click="query='';filter='all'">{{labels.clearFilter}}</Button>
      </div>
      <p v-if="error" role="alert" class="flex items-center gap-2 rounded-lg border border-destructive/20 bg-destructive/5 p-3 text-xs text-destructive">
        <AlertCircle class="size-4 shrink-0"/>{{error}}
      </p>
      <p v-if="observation" role="status" class="rounded-lg border border-border bg-muted/20 p-3 text-sm">{{observation}}</p>
      <div v-if="displayState==='loading'" class="space-y-3" role="status">
        <Skeleton v-for="i in 4" :key="i" class="h-11 w-full"/>
      </div>
      <p v-else-if="displayState!=='ready' || shown.length===0" role="status"
        class="min-h-24 rounded-lg border border-dashed border-border p-6 text-center text-sm text-muted-foreground">
        {{displayState==='ready'?(records.length?labels.noMatch:labels.empty):stateMessage}}
      </p>
      <Table v-else>
        <TableHeader>
          <TableRow>
            <TableHead>{{labels.session}}</TableHead>
            <TableHead>{{labels.operations}}</TableHead>
            <TableHead>{{labels.expires}}</TableHead>
            <TableHead>{{labels.status}}</TableHead>
            <TableHead>{{labels.actions}}</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          <TableRow v-for="item in shown" :key="item.id">
            <TableCell class="min-w-36 break-all font-mono text-xs">{{item.agent_session_uuid}}</TableCell>
            <TableCell class="min-w-36 max-w-72 text-xs">
              <p v-for="operation in item.requested_operations" :key="operation">{{operation}}</p>
              <details v-if="item.requested_resources.length" class="mt-2">
                <summary class="cursor-pointer text-muted-foreground">{{labels.resource}}: {{item.requested_resources.length}}</summary>
                <p v-for="(effect,i) in item.requested_resources" :key="i" class="mt-1 break-all font-mono text-[11px]">{{effect.hand}} / {{effect.tool}} / {{effect.resource.kind}}: {{effect.resource.id}}</p>
              </details>
            </TableCell>
            <TableCell class="min-w-32 text-xs">{{new Date(item.requested_expires_at).toLocaleString(locale)}}</TableCell>
            <TableCell><Badge variant="outline">{{labels[item.status]}}</Badge></TableCell>
            <TableCell>
              <div class="flex flex-wrap gap-1">
                <Button variant="outline" size="sm" :disabled="!canRead||refreshing||mutating" @click="reviewedId=item.id">{{labels.inspectRequest}}</Button>
                <Button v-if="allowAction(item,'approve')" size="sm" @click="requestAction(item,'approve')">{{labels.approve}}</Button>
                <Button v-if="allowAction(item,'deny')" variant="outline" size="sm" @click="requestAction(item,'deny')">{{labels.deny}}</Button>
                <Button v-if="item.status==='approved'&&item.issued_session_uuid" variant="outline" size="sm"
                  :disabled="!canRead||refreshing||mutating" @click="issued=item.issued_session_uuid">{{labels.inspectIssued}}</Button>
                <span v-if="item.status!=='approved'&&!allowAction(item,'approve')&&!allowAction(item,'deny')" class="text-xs text-muted-foreground">—</span>
              </div>
            </TableCell>
          </TableRow>
        </TableBody>
      </Table>
      <p v-if="records.length===50" class="text-xs text-muted-foreground" role="status">{{labels.limited}}</p>
      <p class="text-xs leading-5 text-muted-foreground">{{labels.noSessions}}</p>
    </CardContent>
  </Card>
  <Dialog :open="reviewedId!==null" @update:open="open=>{if(!open)reviewedId=null}">
    <DialogContent class="max-h-[85vh] overflow-y-auto">
      <DialogHeader><DialogTitle>{{labels.inspectRequest}}</DialogTitle><DialogDescription>{{labels.detailNote}}</DialogDescription></DialogHeader>
      <p v-if="refreshing" class="text-sm text-muted-foreground" role="status">{{labels.loading}}</p>
      <div v-else-if="reviewed" class="min-w-0 space-y-4">
        <dl class="grid min-w-0 grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-2 text-xs">
          <dt>{{labels.requestId}}</dt><dd class="break-all font-mono">{{reviewed.id}}</dd>
          <dt>{{labels.requester}}</dt><dd class="break-all font-mono">{{reviewed.requested_by_user_uuid}}</dd>
          <dt>{{labels.session}}</dt><dd class="break-all font-mono">{{reviewed.agent_session_uuid}}</dd>
          <dt>{{labels.status}}</dt><dd>{{labels[reviewed.status]}}</dd>
          <dt>{{labels.version}}</dt><dd>{{reviewed.version}}</dd>
          <dt>{{labels.expires}}</dt><dd>{{new Date(reviewed.requested_expires_at).toLocaleString(locale)}}</dd>
          <dt v-if="reviewed.resolved_by_user_uuid">{{labels.resolver}}</dt><dd v-if="reviewed.resolved_by_user_uuid" class="break-all font-mono">{{reviewed.resolved_by_user_uuid}}</dd>
          <dt v-if="reviewed.issued_session_uuid">{{labels.issuedId}}</dt><dd v-if="reviewed.issued_session_uuid" class="break-all font-mono">{{reviewed.issued_session_uuid}}</dd>
        </dl>
        <h3 class="text-sm font-semibold">{{labels.operations}}</h3>
        <p v-for="operation in reviewed.requested_operations" :key="operation" class="break-all font-mono text-xs">{{operation}}</p>
        <h3 class="text-sm font-semibold">{{labels.resource}}</h3>
        <p v-for="(scope,index) in reviewed.requested_resources" :key="index" class="break-all font-mono text-xs">{{scope.hand}} · {{scope.tool}} · {{scope.action}} · {{scope.resource.kind}}: {{scope.resource.id}}</p>
      </div>
    </DialogContent>
  </Dialog>
  <Dialog :open="issued!==null" @update:open="open=>{if(!open)issued=null}">
    <DialogContent class="max-h-[85vh] overflow-y-auto">
      <DialogHeader><DialogTitle>{{labels.issuedTitle}}</DialogTitle><DialogDescription>{{labels.issuedNote}}</DialogDescription></DialogHeader>
      <SessionInspector v-if="issued&&projectId&&actorId&&proofExpiresAt" :key="issued"
        :project-id="projectId" :session-id="issued" :actor-id="actorId" :proof-expires-at="proofExpiresAt"
        :can-list="canRead" :can-approve="canApprove===true"/>
    </DialogContent>
  </Dialog>
  <Dialog :open="confirmation!==null" @update:open="open=>{if(!open&&!mutating)confirmation=null}">
    <DialogContent>
      <DialogHeader>
        <DialogTitle>{{labels.details}}</DialogTitle>
        <DialogDescription>{{labels.source}}</DialogDescription>
      </DialogHeader>
      <div v-if="confirmation" class="space-y-2 text-sm">
        <p class="break-all font-mono text-xs">{{confirmation.item.id}}</p>
        <p>{{labels.session}}: <span class="break-all font-mono">{{confirmation.item.agent_session_uuid}}</span></p>
        <p>{{labels.operations}}: {{confirmation.item.requested_operations.join(', ')}}</p>
        <p class="flex items-center gap-1 text-xs text-muted-foreground"><Clock class="size-4"/>{{new Date(confirmation.item.requested_expires_at).toLocaleString(locale)}}</p>
        <p class="text-xs text-muted-foreground">{{labels.readOnly}}</p>
      </div>
      <DialogFooter>
        <Button variant="outline" :disabled="mutating" @click="confirmation=null">{{labels.cancel}}</Button>
        <Button :disabled="!confirmation||!allowAction(confirmation.item,confirmation.action)" @click="confirmAction">
          <CheckCircle2 class="mr-1 size-4"/>{{confirmation?.action==='approve'?labels.approve:labels.deny}}
        </Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>
</template>
