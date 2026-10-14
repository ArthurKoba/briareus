<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue"
import { useI18n } from "vue-i18n"
import { readRauthyPanelState, type RauthyPanelState } from "@/features/platform/api/rauthy-oidc"

/** Read-only OIDC identity indicator in the anonymous catalog.
 * An external OAuth subject is NOT a Briareus Platform User or a grant.
 */
const { locale } = useI18n()
const state = ref<RauthyPanelState | { kind: "checking" }>({ kind: "checking" })
let controller: AbortController | null = null

const labels = computed(() => locale.value === "ru" ? {
  checking: "Проверяем сеанс…",
  signedOut: "Гостевой просмотр",
  signedIn: "Учётная запись подтверждена",
  membership: "Права на Project и Team пока не подтверждены",
  unavailable: "Статус входа недоступен",
  retry: "Повторить",
} : {
  checking: "Checking session…",
  signedOut: "Guest browsing",
  signedIn: "Account identity verified",
  membership: "Project and Team permissions are not yet verified",
  unavailable: "Sign-in status unavailable",
  retry: "Retry",
})

async function refresh(): Promise<void> {
  controller?.abort()
  const request = new AbortController()
  controller = request
  state.value = { kind: "checking" }
  const deadline = setTimeout(() => request.abort(), 8000)
  try {
    const result = await readRauthyPanelState(request.signal)
    if (controller === request) {
      state.value = request.signal.aborted ? { kind: "unavailable" } : result
    }
  } finally {
    clearTimeout(deadline)
    if (controller === request) controller = null
  }
}
onMounted(() => { void refresh() })
onBeforeUnmount(() => { controller?.abort(); controller = null })
</script>

<template>
  <div class="flex min-w-0 items-center gap-2 text-xs text-muted-foreground" role="status" aria-live="polite">
    <span class="size-2 shrink-0 rounded-full" :class="state.kind==='signed_in'?'bg-primary':'bg-muted-foreground/50'" aria-hidden="true" />
    <div class="min-w-0">
      <p class="font-medium text-foreground">
        {{state.kind==='checking'?labels.checking:state.kind==='signed_in'?labels.signedIn:state.kind==='signed_out'?labels.signedOut:labels.unavailable}}
      </p>
      <p v-if="state.kind==='signed_in'" class="max-w-[260px] text-[11px] leading-4 text-muted-foreground">{{labels.membership}}</p>
    </div>
    <button v-if="state.kind==='unavailable'" type="button" class="min-h-10 rounded-lg px-2 font-medium text-primary hover:bg-muted focus-visible:outline-2 focus-visible:outline-ring" @click="refresh">{{labels.retry}}</button>
  </div>
</template>
