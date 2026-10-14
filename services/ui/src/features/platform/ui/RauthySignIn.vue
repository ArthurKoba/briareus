<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue"
import { useI18n } from "vue-i18n"
import {
  readRauthyPanelState,
  signOutRauthyPanel,
  type RauthyPanelState,
} from "@/features/platform/api/rauthy-oidc"

const { locale } = useI18n()
const state = ref<RauthyPanelState | { kind: "checking" }>({ kind: "checking" })
const busy = ref(false)
const error = ref(false)
let controller: AbortController | null = null

const labels = computed(() => locale.value === "ru" ? {
  title: "Вход в Briareus",
  checking: "Проверяем подключение авторизации…",
  unavailable: "Вход временно недоступен. Требуется подключение OAuth-клиента и серверной сессии.",
  ready: "Для безопасного входа используется серверный OAuth. Пароль и токены не сохраняются в Control Panel.",
  start: "Войти в Control Panel",
  signedIn: "Учётная запись подтверждена",
  scope: "Права на Projects, Teams и управление MCP ещё не проверены Platform Control.",
  logout: "Завершить сеанс Briareus",
  logoutError: "Не удалось подтвердить отзыв сеанса. Повторите попытку.",
  refresh: "Проверить подключение",
} : {
  title: "Sign in to Briareus",
  checking: "Checking identity-provider connection…",
  unavailable: "Sign-in is temporarily unavailable. The OAuth client or server session is not ready.",
  ready: "Secure sign-in uses server-managed OAuth. Control Panel does not store passwords or tokens.",
  start: "Sign in to Control Panel",
  signedIn: "Account identity verified",
  scope: "Projects, Teams and MCP management privileges have not yet been verified by Platform Control.",
  logout: "End Briareus session",
  logoutError: "Session revocation was not confirmed. Try again.",
  refresh: "Check connection",
})

async function refresh(): Promise<void> {
  controller?.abort()
  const request = new AbortController()
  controller = request
  state.value = { kind: "checking" }
  error.value = false
  const result = await readRauthyPanelState(request.signal)
  if (!request.signal.aborted) {
    state.value = result
    if (controller === request) controller = null
  }
}

async function logout(): Promise<void> {
  if (busy.value) return
  busy.value = true
  error.value = false
  controller?.abort()
  const request = new AbortController()
  controller = request
  const revoked = await signOutRauthyPanel(request.signal)
  if (!request.signal.aborted) {
    if (revoked) state.value = { kind: "signed_out" }
    else error.value = true
    controller = null
  }
  busy.value = false
}

onMounted(() => { void refresh() })
onBeforeUnmount(() => { controller?.abort(); controller = null })
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
    <p v-else-if="state.kind==='unavailable'" class="mt-2 text-sm leading-6 text-muted-foreground" role="status">{{ labels.unavailable }}</p>
    <div v-else-if="state.kind==='signed_in'" class="mt-3 space-y-3" role="status">
      <p class="text-sm font-medium text-foreground">{{ labels.signedIn }}</p>
      <p class="break-all font-mono text-xs text-muted-foreground">{{ state.identity.subject }}</p>
      <p class="text-sm leading-6 text-muted-foreground">{{ labels.scope }}</p>
      <button
        type="button"
        class="min-h-11 w-full rounded-lg border border-border px-4 text-sm font-semibold hover:bg-accent focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring disabled:opacity-50"
        :disabled="busy"
        @click="logout"
      >{{ labels.logout }}</button>
      <p v-if="error" class="text-sm text-destructive" role="alert">{{ labels.logoutError }}</p>
    </div>
    <div v-else class="mt-3 space-y-3">
      <p class="text-sm leading-6 text-muted-foreground">{{ labels.ready }}</p>
      <a
        href="/api/auth/oidc/start"
        class="inline-flex min-h-11 w-full items-center justify-center rounded-lg bg-primary px-4 text-sm font-semibold text-primary-foreground hover:opacity-90 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
      >{{ labels.start }}</a>
    </div>
  </section>
</template>
