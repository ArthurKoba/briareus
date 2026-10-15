<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue"
import { useI18n } from "vue-i18n"
import {
  readRauthyPanelState,
  signOutRauthyPanel,
  type RauthyPanelState,
  type RauthyPanelIdentity,
} from "@/features/platform/api/rauthy-oidc"

type LoginViewState=RauthyPanelState | {kind:"checking"}
const props=defineProps<{
  /** Already checked by the authoritative OIDC panel; do not poll it again. */
  initialState?:RauthyPanelState|null
  /** Parent orchestrates logout and cancels its pending membership read. */
  managedLogout?:boolean
}>()
const emit=defineEmits<{
  logoutRequested:[]
  identity:[value:RauthyPanelIdentity|null]
  state:[value:LoginViewState]
}>()
const { locale } = useI18n()

const state = ref<RauthyPanelState | { kind: "checking" }>({ kind: "checking" })
const busy = ref(false)
const error = ref(false)
const logoutFailure = ref<"forbidden" | "unavailable" | "uncertain" | null>(null)
const hadSession = ref(false)
const ended = ref(false)
let lastCheckedAt = 0
let expiryTimer: ReturnType<typeof setTimeout> | null = null
let controller: AbortController | null = null

function acceptState(next:LoginViewState):void {
  state.value=next
  emit("state",next)
  if(next.kind==="signed_in"){
    emit("identity",next.identity)
    hadSession.value=true
    ended.value=false
    if(expiryTimer!==null)clearTimeout(expiryTimer)
    // OidcPanelPage already owns freshness/visibility checks whenever
    // it supplies a verified browser snapshot. Do not independently poll
    // the same session a second time from the child login component.
    if(!props.initialState){
      const remaining=Date.parse(next.identity.expires_at)-Date.now()
      expiryTimer=setTimeout(()=>{void refresh()},Math.max(1000,Math.min(remaining,900000)))
    }
  }else{
    emit("identity",null)
    if(expiryTimer!==null){clearTimeout(expiryTimer);expiryTimer=null}
    if(next.kind==="signed_out"&&hadSession.value){
      ended.value=true
      hadSession.value=false
    }
  }
}
const labels = computed(() => locale.value === "ru" ? {
  title: "Вход в Briareus",
  checking: "Проверяем подключение авторизации…",
  unavailable: "Вход временно недоступен. Требуется подключение OAuth-клиента и серверной сессии.",
  ready: "Вход выполняется только в Briareus Control Panel. Сеанс Rauthy проверяется сервером, без хранения паролей и токенов в UI.",
  signedIn: "Учётная запись подтверждена",
  scope: "Права на Projects, Teams и управление MCP ещё не проверены Platform Control.",
  logout: "Завершить сеанс Briareus",
  logoutError: "Не удалось подтвердить отзыв сеанса. Его статус неизвестен — повторите проверку.",
  forbidden: "Доступ запрещён сервером. Проверьте параметры сеанса.",
  ended: "Сеанс завершён или отозван. Войдите снова.",
  revokedFailure: "Сервер не подтвердил завершение сеанса; действие могло не выполниться.",
  refresh: "Проверить подключение",
} : {
  title: "Sign in to Briareus",
  checking: "Checking identity-provider connection…",
  unavailable: "Sign-in is temporarily unavailable. The OAuth client or server session is not ready.",
  ready: "Sign-in takes place inside Briareus Control Panel. The backend verifies Rauthy identity; the UI stores no passwords or tokens.",
  signedIn: "Account identity verified",
  scope: "Projects, Teams and MCP management privileges have not yet been verified by Platform Control.",
  logout: "End Briareus session",
  logoutError: "Session revocation was not confirmed; its status is unknown.",
  forbidden: "Access denied by the server. Verify your session.",
  ended: "Session ended or was revoked. Please sign in again.",
  revokedFailure: "Server did not confirm session revocation; the operation may not have completed.",
  refresh: "Check connection",
})

async function refresh(): Promise<void> {
  if(busy.value)return
  lastCheckedAt=Date.now()
  controller?.abort()
  if(expiryTimer!==null){clearTimeout(expiryTimer);expiryTimer=null}
  const request = new AbortController()
  controller = request
  acceptState({kind:"checking"})
  error.value = false
  logoutFailure.value=null
  const deadline = setTimeout(() => request.abort(), 8000)
  try {
    const result = await readRauthyPanelState(request.signal)
    if (controller === request) {
      acceptState(request.signal.aborted
        ? {kind:"unavailable",reason:"network"} : result)
    }
  } finally {
    clearTimeout(deadline)
    if (controller === request) controller = null
  }
}

async function logout(): Promise<void> {
  if (busy.value) return
  if(props.managedLogout){emit("logoutRequested");return}
  busy.value = true
  error.value = false
  controller?.abort()
  const request = new AbortController()
  controller = request
  const deadline = setTimeout(() => request.abort(), 8000)
  try {
    const outcome = await signOutRauthyPanel(request.signal)
    if (controller === request) {
      if (!request.signal.aborted && outcome.kind === "revoked"){
        acceptState({kind:"signed_out"})
        hadSession.value=false
        ended.value=false
      }else {
        error.value=true
        logoutFailure.value=outcome.kind==="revoked"?"uncertain":outcome.kind
        acceptState({kind:"unavailable",reason:"session_unavailable"})
      }
    }
  } finally {
    clearTimeout(deadline)
    if (controller === request) controller = null
    busy.value = false
  }
}

function onVisibility():void {
  if(props.initialState||busy.value)return
  if(document.visibilityState==="visible"&&Date.now()-lastCheckedAt>10000)void refresh()
}
onMounted(() => {
  if(props.initialState){
    lastCheckedAt=Date.now()
    acceptState(props.initialState)
  }else void refresh()
  document.addEventListener("visibilitychange",onVisibility)
})
watch(()=>props.initialState,next=>{
  if(!next)return
  // If the parent reconciles the authoritative provider session, reject
  // any older in-flight child request rather than overwrite newer evidence.
  controller?.abort()
  controller=null
  lastCheckedAt=Date.now()
  acceptState(next)
})
onBeforeUnmount(() => {
  emit("identity",null)
  controller?.abort(); controller=null
  if(expiryTimer!==null)clearTimeout(expiryTimer)
  document.removeEventListener("visibilitychange",onVisibility)
})
</script>

<template>
  <section class="mt-5 rounded-xl border border-border bg-card p-4 sm:p-5" aria-labelledby="rauthy-sign-in-title">
    <div class="flex flex-wrap items-center justify-between gap-2">
      <h2 id="rauthy-sign-in-title" class="text-sm font-semibold text-foreground">{{ labels.title }}</h2>
      <button
        v-if="state.kind==='unavailable'"
        type="button"
        class="rounded-md px-2 py-1 text-xs text-primary underline-offset-2 hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
        @click="refresh"
      >{{ labels.refresh }}</button>
    </div>
    <p v-if="state.kind==='checking'" class="mt-2 text-sm text-muted-foreground" role="status">{{ labels.checking }}</p>
    <p v-else-if="state.kind==='unavailable'" class="mt-2 text-sm leading-6 text-muted-foreground" role="status">{{ state.reason==="forbidden"?labels.forbidden:labels.unavailable }}</p>
    <div v-else-if="state.kind==='signed_in'" class="mt-3 space-y-3" role="status">
      <p class="text-sm font-medium text-foreground">{{ labels.signedIn }}</p>
      <p class="text-sm leading-6 text-muted-foreground">{{ labels.scope }}</p>
      <button
        type="button"
        class="min-h-11 w-full rounded-lg border border-border px-4 text-sm font-semibold hover:bg-accent focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring disabled:opacity-50"
        :disabled="busy"
        @click="logout"
      >{{ labels.logout }}</button>
    </div>
    <div v-else class="mt-3 space-y-3">
      <p v-if="ended" class="text-sm leading-6 text-foreground" role="status">{{ labels.ended }}</p>
      <p v-else class="text-sm leading-6 text-muted-foreground">{{ labels.ready }}</p>
    </div>
    <p v-if="error" class="mt-3 text-sm text-destructive" role="alert">{{ logoutFailure==="forbidden"?labels.forbidden:logoutFailure==="unavailable"?labels.revokedFailure:labels.logoutError }}</p>
  </section>
</template>
