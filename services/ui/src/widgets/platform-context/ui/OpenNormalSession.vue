<script setup lang="ts">
import { computed, onBeforeUnmount, ref, shallowRef, watch } from "vue"
import { useI18n } from "vue-i18n"
import { useProofLifetime } from "@/shared/lib/use-proof-lifetime"
import { Clock3, FolderKey, ShieldCheck } from "lucide-vue-next"
import { createSessionOpenRecovery, openVerifiedNormalSession, SessionInspector, type PendingSessionOpen, type SessionOpenRecovery, type ElevationPolicy, type NormalSession } from "@/features/agent-sessions"
import { Card,CardContent,CardHeader,CardTitle } from "@/shared/ui/card"
import { Button } from "@/shared/ui/button"
import { Badge } from "@/shared/ui/badge"
import { Input } from "@/shared/ui/input"
import { Skeleton } from "@/shared/ui/skeleton"

type Fresh = "authorized" | "unauthorized" | "forbidden" | "unavailable"
const props=withDefaults(defineProps<{
  projectId?:string
  actorId?:string
  ownerKey?:string
  recovery?:SessionOpenRecovery
  proofExpiresAt?:string
  canOpen?:boolean
  canApprove?:boolean
  verifyUser?: (signal:AbortSignal)=>Promise<Fresh>
  designPreview?:boolean
}>(),{designPreview:false})
const {locale}=useI18n()
const policy=ref<ElevationPolicy>("requestable")
const label=ref("")
const busy=ref(false)
const result=ref<NormalSession|null>(null)
const resultCurrent=useProofLifetime(()=>result.value?.hard_expires_at)
const expired=computed(()=>result.value!==null&&!resultCurrent.value)
const recovered=ref(false)
const inspectCurrent=ref(false)
const outcome=ref("")
const pending=shallowRef<PendingSessionOpen|null>(null)
const localRecovery=createSessionOpenRecovery()
const recovery=computed(()=>props.recovery??localRecovery)
let current:AbortController|null=null
let generation=0
const words=computed(()=>locale.value==="ru"?{
  title:"Обычная AgentSession",
  description:"Создание серверного сеанса в выбранном проекте. Это не выдача расширенных прав.",
  fixed:"Без повышения",requestable:"С запросом повышения",
  label:"Метка сеанса (необязательно)",placeholder:"Например, импорт исходников",
  create:"Открыть сеанс",opening:"Проверяем права и открываем сеанс…",
  inactive:"Вход и доступ к проекту должны быть подтверждены сервером",
  unavailable:"Сервис сеансов недоступен. Новый сеанс не подтверждён.",
  uncertain:"Ответ на создание не подтверждён. Сохранён исходный запрос; новый сеанс автоматически не создаётся.",
  retry:"Повторить исходный запрос",
  recoveryExpired:"Срок восстановления исходного запроса истёк. Проверьте список сеансов; повторное создание автоматически не выполняется.",
  retained:"Незавершённый запрос сохранён. Повтор использует тот же ключ и параметры после новой проверки прав.",
  denied:"Сервер отказал в доступе к выбранному проекту",
  signedOut:"Сеанс входа завершён — авторизуйтесь заново",
  conflict:"Состояние на сервере изменилось — перепроверьте права",
  invalid:"Неверные параметры запроса или неподтверждённый ответ сервера",
  opened:"Новый обычный сеанс подтверждён сервером",
  recovered:"Результат исходного создания восстановлен",
  expires:"Завершится",revision:"Ревизия",operations:"Разрешённые операции",
  current:"Проверить текущее состояние сеанса",
  noHistory:"Это ответ последнего создания. Для текущего серверного списка перейдите на вкладку «Текущие сеансы».",
  noElevation:"Здесь создаётся только обычный сеанс. Отзыв доступен на вкладке «Текущие сеансы» по серверной ревизии.",
  expired:"Время сеанса истекло. Текущее состояние сервера неизвестно.",
  sample:"В дизайн-превью кнопка не обращается к серверу.",
}:{
  title:"Normal AgentSession",
  description:"Create a server-owned normal session in the selected project. This is not an elevation grant.",
  fixed:"Fixed permissions",requestable:"Allow elevation requests",
  label:"Session label (optional)",placeholder:"For example, source import",
  create:"Open session",opening:"Revalidating rights and opening session…",
  inactive:"Sign-in and Project access must be verified by the server",
  unavailable:"Session owner unavailable; no new session confirmed.",
  uncertain:"Creation response is unconfirmed. The original request is retained; no new session is created automatically.",
  retry:"Retry original request",
  recoveryExpired:"The original request recovery window elapsed. Check current sessions; no replacement is created automatically.",
  retained:"An unresolved request is retained. Retry keeps its key and payload after verifying current permissions again.",
  denied:"Server denied access to the selected project",
  signedOut:"Login session ended — sign in again",
  conflict:"Server state changed — refresh the permission proof",
  invalid:"Invalid request or unverified response from server",
  opened:"New normal session confirmed by the server",
  recovered:"Original creation result recovered",
  expires:"Expires",revision:"Revision",operations:"Allowed operations",
  current:"Inspect current session state",
  noHistory:"This is the last create response. Switch to Current sessions for the server-owned list.",
  noElevation:"Only a normal session is created here. Revocation is available from Current sessions with the server grant revision.",
  expired:"Session time elapsed. Current server state is unknown.",
  sample:"Design preview never invokes the server.",
})
const proofCurrent=useProofLifetime(()=>props.proofExpiresAt)
const eligible=computed(()=>!props.designPreview&&props.canOpen===true&&typeof props.verifyUser==="function"
  &&typeof props.projectId==="string"&&typeof props.actorId==="string"&&typeof props.ownerKey==="string"&&typeof props.proofExpiresAt==="string"
  &&proofCurrent.value&&Date.parse(props.proofExpiresAt)>Date.now()&&!busy.value)
function stop():void{
  ++generation
  current?.abort()
  current=null
}
function reset():void {
  stop();result.value=null;inspectCurrent.value=false;recovered.value=false;outcome.value="";busy.value=false
  pending.value=props.ownerKey&&props.projectId?recovery.value.get(props.ownerKey,props.projectId):null
  policy.value=pending.value?.command.policy??"requestable"
  label.value=pending.value?.command.label??""
}
watch(()=>[props.projectId,props.actorId,props.ownerKey,props.recovery,props.canOpen,props.designPreview],reset,{flush:"sync",immediate:true})
watch(()=>props.proofExpiresAt,value=>{
  if(!value||!(Date.parse(value)>Date.now()))reset()
},{flush:"sync"})
watch(proofCurrent,current=>{if(!current)reset()},{flush:"sync"})
onBeforeUnmount(()=>{stop();localRecovery.clear();pending.value=null;result.value=null})
async function create(retry=false):Promise<void>{
  if(!eligible.value||!props.verifyUser||!props.projectId||!props.ownerKey)return
  const saved=pending.value
  if((retry&&!saved)||(!retry&&saved))return
  current?.abort()
  const request=new AbortController(),run=++generation
  const project=props.projectId,actor=props.actorId,owner=props.ownerKey,journal=recovery.value
  current=request;busy.value=true;outcome.value=""
  const timeout=setTimeout(()=>request.abort(),9000)
  try{
    result.value=null;inspectCurrent.value=false
    const next=await openVerifiedNormalSession({
      policy:policy.value,label:label.value,saved,journal,signal:request.signal,
      verify:props.verifyUser,
      context:()=>run===generation&&props.projectId===project&&props.actorId===actor&&props.ownerKey===owner?{
        ownerKey:owner,projectId:project,actorId:actor??"",canOpen:props.canOpen===true&&proofCurrent.value,
        proofExpiresAt:props.proofExpiresAt??"",
      }:null,
    })
    if(run!==generation)return
    pending.value=journal.get(owner,project)
    if(next.kind!=="created"){
      outcome.value=next.code==="SESSION_RECOVERY_WINDOW_ELAPSED"?words.value.recoveryExpired:
        next.kind==="unauthorized"?words.value.signedOut:
        next.kind==="forbidden"?words.value.denied:next.kind==="conflict"?words.value.conflict:
        next.kind==="invalid"?words.value.invalid:next.kind==="uncertain"?words.value.uncertain:words.value.unavailable
      return
    }
    result.value=next.session;recovered.value=retry
  }finally{
    clearTimeout(timeout)
    if(current===request){current=null;busy.value=false}
  }
}

</script>
<template>
  <Card class="min-w-0">
    <CardHeader>
      <CardTitle class="flex items-center gap-2 text-sm">
        <FolderKey class="size-4" aria-hidden="true"/>{{words.title}}
      </CardTitle>
      <p class="text-xs leading-5 text-muted-foreground">{{words.description}}</p>
    </CardHeader>
    <CardContent class="space-y-4">
      <div class="flex flex-wrap gap-2" role="group" :aria-label="words.title">
        <Button type="button" size="sm" :variant="policy==='requestable'?'default':'outline'"
          :aria-pressed="policy==='requestable'" :disabled="busy||pending!==null" @click="policy='requestable'">{{words.requestable}}</Button>
        <Button type="button" size="sm" :variant="policy==='fixed'?'default':'outline'"
          :aria-pressed="policy==='fixed'" :disabled="busy||pending!==null" @click="policy='fixed'">{{words.fixed}}</Button>
      </div>
      <label class="block max-w-md space-y-2 text-xs font-semibold">
        <span>{{words.label}}</span>
        <Input v-model="label" :disabled="busy||pending!==null" :placeholder="words.placeholder"
          maxlength="128" autocomplete="off" />
      </label>
      <p class="text-xs text-muted-foreground">{{designPreview?words.sample:words.noElevation}}</p>
      <Button :disabled="!eligible||pending!==null" @click="create(false)">
        <ShieldCheck class="mr-1 size-4" aria-hidden="true"/>{{words.create}}
      </Button>
      <div v-if="pending" class="space-y-2 rounded-lg border border-border p-3">
        <p class="text-xs leading-5 text-muted-foreground" role="status">{{words.retained}}</p>
        <Button variant="outline" :disabled="!eligible" @click="create(true)">{{words.retry}}</Button>
      </div>
      <div v-if="busy" class="space-y-2" role="status">
        <p class="text-xs text-muted-foreground">{{words.opening}}</p>
        <Skeleton class="h-10 w-full"/>
      </div>
      <p v-if="outcome" class="rounded-lg border border-border bg-muted/30 p-3 text-sm text-foreground"
        role="alert">{{outcome}}</p>
      <p v-if="!eligible&&!busy&&!result" class="text-xs text-muted-foreground" role="status">
        {{designPreview?words.sample:words.inactive}}
      </p>
      <div v-if="result" class="space-y-3 rounded-xl border border-border bg-muted/20 p-4" role="status">
        <div class="flex flex-wrap items-center justify-between gap-2">
          <p class="text-sm font-semibold">{{expired?words.expired:recovered?words.recovered:words.opened}}</p>
          <Badge variant="outline">{{result.elevation_policy==="fixed"?words.fixed:words.requestable}}</Badge>
        </div>
        <p class="break-all font-mono text-xs">{{result.session_uuid}}</p>
        <p class="text-xs text-muted-foreground">{{words.revision}}: {{result.revision}}</p>
        <p class="flex items-center gap-1 text-xs text-muted-foreground">
          <Clock3 class="size-4" aria-hidden="true"/>{{words.expires}}:
          {{new Date(result.hard_expires_at).toLocaleString(locale)}}
        </p>
        <p class="text-xs">{{words.operations}}: {{result.operations.join(", ")}}</p>
        <p class="text-xs text-muted-foreground">{{words.noHistory}}</p>
        <Button type="button" variant="outline" :disabled="!eligible" @click="inspectCurrent=!inspectCurrent" :aria-expanded="inspectCurrent">{{words.current}}</Button>
        <SessionInspector v-if="inspectCurrent&&projectId&&actorId&&proofExpiresAt" :key="result.session_uuid"
          :project-id="projectId" :session-id="result.session_uuid" :actor-id="actorId" :proof-expires-at="proofExpiresAt"
          :can-list="canOpen===true" :can-approve="canApprove===true"/>

      </div>
    </CardContent>
  </Card>
</template>
