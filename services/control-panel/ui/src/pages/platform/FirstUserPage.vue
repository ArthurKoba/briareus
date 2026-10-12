<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from "vue"
import { useI18n } from "vue-i18n"
import { checkOidcReadiness, type OidcReadiness } from "@/features/platform/api/oidc-readiness"

const { t } = useI18n()
const status = ref<OidcReadiness | "checking">("checking")
let checkAbort: AbortController | null = null
let generation = 0

async function refreshReadiness() {
  checkAbort?.abort()
  const controller = new AbortController()
  checkAbort = controller
  const current = ++generation
  status.value = "checking"
  const next = await checkOidcReadiness(controller.signal)
  if (!controller.signal.aborted && generation === current) {
    status.value = next
    checkAbort = null
  }
}
onMounted(() => { void refreshReadiness() })
onBeforeUnmount(() => { ++generation; checkAbort?.abort(); checkAbort = null })
</script>
<template>
  <section class="mx-auto grid w-full max-w-[1100px] overflow-hidden rounded-[28px] border border-border bg-card shadow-[0_32px_100px_-40px_rgba(8,35,55,.4)] lg:min-h-[600px] lg:grid-cols-[.9fr_1.1fr]" aria-labelledby="oidc-login-title">
    <aside class="relative isolate overflow-hidden bg-[#101f31] px-6 py-9 text-slate-100 sm:px-10 lg:flex lg:flex-col lg:justify-between lg:px-12 lg:py-12">
      <div class="pointer-events-none absolute -right-32 -top-36 -z-10 size-[420px] rounded-full bg-teal-400/20 blur-[95px]" aria-hidden="true" />
      <div class="pointer-events-none absolute -bottom-40 -left-24 -z-10 size-[390px] rounded-full bg-sky-500/20 blur-[95px]" aria-hidden="true" />
      <div class="relative z-10 flex items-center gap-3">
        <span class="grid size-11 shrink-0 place-items-center rounded-xl border border-teal-300/30 bg-teal-300/10 text-lg font-black text-teal-200" aria-hidden="true">B</span>
        <div>
          <p class="text-[11px] font-bold uppercase tracking-[.18em] text-teal-200/80">Briareus</p>
          <p class="text-base font-semibold leading-6">Control Panel</p>
        </div>
      </div>
      <div class="relative z-10 mt-12 lg:my-12">
        <span class="inline-flex rounded-full border border-teal-200/25 bg-teal-200/10 px-3 py-1 text-[11px] font-semibold uppercase tracking-widest text-teal-100">{{ t('firstUser.workspaceLabel') }}</span>
        <h2 class="mt-5 max-w-sm text-3xl font-semibold leading-tight tracking-tight sm:text-4xl">{{ t('firstUser.heroTitle') }}</h2>
        <p class="mt-4 max-w-sm text-sm leading-7 text-slate-300">{{ t('firstUser.heroDescription') }}</p>
      </div>
      <div class="relative z-10 mt-8 border-t border-white/15 pt-5 text-xs leading-6 text-slate-400">{{ t('oidc.serverAuthority') }}</div>
    </aside>
    <div class="flex min-w-0 flex-col justify-center px-5 py-9 sm:px-10 sm:py-12 lg:px-14">
      <div class="mb-8">
        <p class="mb-2 text-xs font-bold uppercase tracking-widest text-primary">{{ t('firstUser.firstStep') }}</p>
        <h1 id="oidc-login-title" class="text-2xl font-semibold tracking-tight text-foreground sm:text-3xl">{{ t('oidc.title') }}</h1>
        <p class="mt-3 text-sm leading-7 text-muted-foreground">{{ t('oidc.description') }}</p>
      </div>
      <div class="rounded-2xl border border-border bg-muted/40 p-5 sm:p-6" role="status" aria-live="polite" aria-atomic="true">
        <div class="mb-3 flex items-center gap-3">
          <span class="grid size-10 shrink-0 place-items-center rounded-xl bg-primary/10 text-lg font-bold text-primary" aria-hidden="true">S</span>
          <div>
            <p class="text-sm font-semibold text-foreground">{{ t('oidc.provider') }}</p>
            <p class="mt-1 text-xs text-muted-foreground">OpenID Connect · Authorization Code + PKCE</p>
          </div>
        </div>
        <p v-if="status==='checking'" class="text-sm leading-6 text-muted-foreground">{{ t('oidc.checking') }}</p>
        <p v-else-if="status==='configured'" class="text-sm leading-6 text-muted-foreground">{{ t('oidc.configuredButNotEnabled') }}</p>
        <p v-else-if="status==='invalid'" class="text-sm leading-6 text-destructive">{{ t('oidc.invalidConfiguration') }}</p>
        <p v-else class="text-sm leading-6 text-muted-foreground">{{ t('oidc.notConnected') }}</p>
      </div>
      <!-- The BFF has published metadata discovery only; no accepted login/start,
           callback, session or logout browser route exists yet. NEVER guess a
           provider URL or start raw PKCE against an unverified redirect URI. -->
      <button type="button" class="mt-5 flex min-h-12 w-full items-center justify-center rounded-xl bg-primary px-4 py-3 text-sm font-semibold text-primary-foreground opacity-60" disabled :aria-label="t('oidc.signInPending')">{{ t('oidc.signInPending') }}</button>
      <button type="button" class="mt-3 w-full rounded-xl border border-border px-4 py-3 text-sm font-medium transition hover:bg-accent focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring disabled:opacity-50" :disabled="status==='checking'" @click="refreshReadiness">{{ t('oidc.checkAgain') }}</button>
      <p class="mt-4 text-xs leading-6 text-muted-foreground">{{ t('oidc.upstreamMfa') }}</p>
      <div class="mt-8 border-t border-border pt-5 text-center text-sm text-muted-foreground">
        <a href="/" class="inline-flex min-h-10 items-center gap-2 rounded-lg px-2 text-primary underline-offset-4 hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring">← {{ t('app.publicWebsite') }}</a>
      </div>
    </div>
  </section>
</template>
