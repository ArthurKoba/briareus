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
  title: "Вход в Control Panel",
  checking: "Проверяем сеанс…",
  unavailable: "Не удалось проверить сеанс.",
  ready: "Вы не вошли. Вход пока недоступен.",
  signedIn: "Сеанс подтверждён.",
  scope: "Проверяем доступ к проектам.",
  logout: "Выйти",
  logoutError: "Выход не подтверждён. Проверьте сеанс ещё раз.",
  forbidden: "Доступ не подтверждён.",
  ended: "Сеанс завершён.",
  revokedFailure: "Не удалось подтвердить выход.",
  refresh: "Проверить сеанс",
} : {
  title: "Control Panel sign-in",
  checking: "Checking session…",
  unavailable: "Unable to verify the session.",
  ready: "You are signed out. Sign-in is not available yet.",
  signedIn: "Session verified.",
  scope: "Checking Project access.",
  logout: "Sign out",
  logoutError: "Sign-out was not confirmed. Check your session again.",
  forbidden: "Access was not verified.",
  ended: "Session ended.",
  revokedFailure: "Unable to confirm sign-out.",
  refresh: "Check session",
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
  <section class="rounded-2xl border border-border bg-card p-5 sm:p-7"
    aria-labelledby="rauthy-sign-in-title">
    <h1 id="rauthy-sign-in-title" class="text-xl font-semibold text-foreground">{{labels.title}}</h1>
    <p v-if="state.kind==='checking'" role="status" class="mt-4 text-sm text-muted-foreground">{{labels.checking}}</p>
    <div v-else-if="state.kind==='signed_in'" class="mt-4 space-y-4">
      <p role="status" class="text-sm font-medium">{{labels.signedIn}}</p>
      <p class="text-sm text-muted-foreground">{{labels.scope}}</p>
      <button type="button"
        class="min-h-11 w-full rounded-lg border border-border px-4 text-sm font-medium hover:bg-accent focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring disabled:opacity-50"
        :disabled="busy" @click="logout">{{labels.logout}}</button>
    </div>
    <div v-else class="mt-4 space-y-4">
      <p role="status" class="text-sm text-muted-foreground">
        {{state.kind==='unavailable'?(state.reason==='forbidden'?labels.forbidden:labels.unavailable):
          ended?labels.ended:labels.ready}}
      </p>
      <button type="button"
        class="min-h-11 w-full rounded-lg border border-border px-4 text-sm font-medium hover:bg-accent focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring disabled:opacity-50"
        :disabled="busy" @click="refresh">{{labels.refresh}}</button>
    </div>
    <p v-if="error" role="alert" class="mt-3 text-sm text-destructive">
      {{logoutFailure==="forbidden"?labels.forbidden:logoutFailure==="unavailable"?labels.revokedFailure:labels.logoutError}}
    </p>
  </section>
</template>
