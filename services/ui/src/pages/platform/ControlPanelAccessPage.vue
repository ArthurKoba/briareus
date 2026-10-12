<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from "vue"
import { setLocale } from "@/shared/i18n"
import { useUiPreferences } from "@/shared/lib/preferences"
import { useI18n } from "vue-i18n"
import { checkControlPanelAccess, type ControlPanelAccessState } from "@/features/platform/api/control-panel-access"

const { t } = useI18n()
const { locale, theme } = useUiPreferences()
function toggleTheme() {
  theme.value = theme.value === "dark" ? "light" : "dark"
}
const state = ref<ControlPanelAccessState>("checking")
let controller: AbortController | null = null
let generation = 0
async function verifyApi() {
  controller?.abort()
  const current = new AbortController()
  controller = current
  const serial = ++generation
  state.value = "checking"
  const result = await checkControlPanelAccess(current.signal)
  if (!current.signal.aborted && serial === generation) {
    state.value = result
    controller = null
  }
}
onMounted(() => { void verifyApi() })
onBeforeUnmount(() => { ++generation; controller?.abort(); controller = null })
</script>
<template>
  <section class="mx-auto grid w-full max-w-[1100px] overflow-hidden rounded-[28px] border border-border bg-card shadow-[0_32px_100px_-40px_rgba(8,35,55,.4)] lg:min-h-[600px] lg:grid-cols-[.9fr_1.1fr]" aria-labelledby="control-panel-login-title">
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
        <span class="inline-flex rounded-full border border-teal-200/25 bg-teal-200/10 px-3 py-1 text-[11px] font-semibold uppercase tracking-widest text-teal-100">{{ t('panelAccess.workspaceLabel') }}</span>
        <h2 class="mt-5 max-w-sm text-3xl font-semibold leading-tight tracking-tight sm:text-4xl">{{ t('panelAccess.heroTitle') }}</h2>
        <p class="mt-4 max-w-sm text-sm leading-7 text-slate-300">{{ t('panelAccess.heroDescription') }}</p>
      </div>
      <div class="relative z-10 mt-8 border-t border-white/15 pt-5 text-xs leading-6 text-slate-400">{{ t('panelAccess.permissionNotice') }}</div>
    </aside>
    <div class="flex min-w-0 flex-col justify-center px-5 py-9 sm:px-10 sm:py-12 lg:px-14">
      <div class="mb-7 flex flex-wrap items-center justify-end gap-3">
        <div class="inline-flex rounded-lg border border-border p-0.5" role="group" :aria-label="t('panelAccess.language')">
          <button type="button" class="min-h-10 min-w-11 rounded-md px-3 text-xs font-semibold transition focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring" :class="locale==='ru'?'bg-primary text-primary-foreground':'text-muted-foreground hover:bg-accent hover:text-foreground'" :aria-pressed="locale==='ru'" lang="ru" @click="setLocale('ru')">RU</button>
          <button type="button" class="min-h-10 min-w-11 rounded-md px-3 text-xs font-semibold transition focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring" :class="locale==='en'?'bg-primary text-primary-foreground':'text-muted-foreground hover:bg-accent hover:text-foreground'" :aria-pressed="locale==='en'" lang="en" @click="setLocale('en')">EN</button>
        </div>
        <button type="button" class="min-h-11 rounded-lg border border-border px-3 text-xs font-semibold text-muted-foreground transition hover:bg-accent hover:text-foreground focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring" :aria-label="theme==='dark'?t('panelAccess.switchToLight'):t('panelAccess.switchToDark')" @click="toggleTheme">{{ theme==='dark'?t('panelAccess.light'):t('panelAccess.dark') }}</button>
      </div>
      <div class="mb-8">
        <p class="mb-2 text-xs font-bold uppercase tracking-widest text-primary">{{ t('panelAccess.firstStep') }}</p>
        <h1 id="control-panel-login-title" class="text-2xl font-semibold tracking-tight text-foreground sm:text-3xl">{{ t('panelAccess.title') }}</h1>
        <p class="mt-3 text-sm leading-7 text-muted-foreground">{{ t('panelAccess.description') }}</p>
      </div>
      <div class="rounded-2xl border border-border bg-muted/40 p-5 sm:p-6" role="status" aria-live="polite" aria-atomic="true">
        <div class="mb-3 flex items-center gap-3">
          <span class="grid size-10 shrink-0 place-items-center rounded-xl bg-primary/10 text-lg font-bold text-primary" aria-hidden="true">B</span>
          <p class="text-sm font-semibold text-foreground">{{ t('panelAccess.connectionTitle') }}</p>
        </div>
        <p v-if="state==='checking'" class="text-sm leading-6 text-muted-foreground">{{ t('panelAccess.checking') }}</p>
        <p v-else-if="state==='signed_out'" class="text-sm leading-6 text-muted-foreground">{{ t('panelAccess.signedOut') }}</p>
        <p v-else-if="state==='denied'" class="text-sm leading-6 text-muted-foreground">{{ t('panelAccess.denied') }}</p>
        <p v-else-if="state==='unverified'" class="text-sm leading-6 text-muted-foreground">{{ t('panelAccess.unverified') }}</p>
        <p v-else class="text-sm leading-6 text-muted-foreground">{{ t('panelAccess.unavailable') }}</p>
      </div>
      <!-- Backend must first publish verified session creation, callback,
           current User and logout routes. Never derive auth URLs in UI. -->
      <div class="mt-5 grid grid-cols-1 gap-3 sm:grid-cols-2">
        <button type="button" disabled class="min-h-12 rounded-xl bg-primary px-4 py-3 text-sm font-semibold text-primary-foreground opacity-60" :aria-label="t('panelAccess.signInPending')">{{ t('panelAccess.signInPending') }}</button>
        <button type="button" disabled class="min-h-12 rounded-xl border border-border px-4 py-3 text-sm font-medium text-muted-foreground opacity-60">{{ t('panelAccess.registrationPending') }}</button>
      </div>
      <button type="button" class="mt-4 w-full rounded-xl border border-border px-4 py-3 text-sm font-medium transition hover:bg-accent focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring disabled:opacity-50" :disabled="state==='checking'" @click="verifyApi">{{ t('panelAccess.retry') }}</button>
      <p class="mt-4 text-xs leading-6 text-muted-foreground">{{ t('panelAccess.accountServices') }}</p>
      <div class="mt-8 border-t border-border pt-5 text-center text-sm text-muted-foreground">
        <a href="/" class="inline-flex min-h-10 items-center gap-2 rounded-lg px-2 text-primary underline-offset-4 hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring">← {{ t('app.publicWebsite') }}</a>
      </div>
    </div>
  </section>
</template>
