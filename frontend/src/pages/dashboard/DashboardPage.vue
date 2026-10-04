<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue"
import { useI18n } from "vue-i18n"

import { managementApi, type DashboardState } from "@/shared/api/management"
import { eventBus, type BusEvent } from "@/shared/events/bus"
import { formatBytes } from "@/shared/lib/format"
import PageHeader from "@/shared/ui/PageHeader.vue"
import RefreshAction from "@/shared/ui/RefreshAction.vue"
import StatCard from "@/shared/ui/StatCard.vue"

const { t } = useI18n()
const data = ref<DashboardState | null>(null)
const loading = ref(false)
const error = ref("")
let unsubscribe: undefined | (() => void)
const synced = ref(false)
const liveTransport = computed(() => eventBus.state.enabled && eventBus.state.status === "connected")
const staleSources = computed(() => {
  if (!data.value) return [] as string[]
  const items: string[] = []
  if (data.value.workspace_meta?.stale === true || data.value.workspace_meta?.status === "error") items.push(String(t("dashboard.workspace")))
  if (data.value.analysis_meta?.stale === true || data.value.analysis_meta?.status === "error") items.push(String(t("dashboard.analysis")))
  return items
})

let eventEpoch = 0
let loadRun = 0

function accept(event: BusEvent): void {
  if (event.type !== "snapshot") return
  const next = event.data as DashboardState
  if (!next.accounts || !next.calls || !next.oauth || !next.workspace || !next.analysis) return
  eventEpoch += 1
  data.value = next
  synced.value = liveTransport.value
  error.value = ""
}

async function load(): Promise<void> {
  const run = ++loadRun
  const startedAtEpoch = eventEpoch
  loading.value = true
  error.value = ""
  try {
    const snapshot = await managementApi.dashboard()
    if (run !== loadRun) return
    // A newer remote snapshot always wins over a slower REST bootstrap/refresh.
    if (startedAtEpoch === eventEpoch) data.value = snapshot
  } catch (caught) {
    if (run === loadRun) error.value = caught instanceof Error ? caught.message : "Unable to load dashboard"
  } finally {
    if (run === loadRun) loading.value = false
  }
}

watch(liveTransport, (live) => { if (!live) synced.value = false })

onMounted(() => {
  // Subscribe before bootstrap so a fresh remote snapshot cannot be missed.
  unsubscribe = eventBus.subscribe("system.metrics", accept)
  void load()
})
onBeforeUnmount(() => unsubscribe?.())
</script>

<template>
  <div class="space-y-6">
    <PageHeader :title="t('nav.dashboard')" :description="t('dashboard.description')">
      <RefreshAction :synced="synced" :loading="loading" @refresh="load" />
    </PageHeader>

    <p v-if="error" class="rounded-lg border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-destructive">
      {{ error }}
    </p>
    <p v-if="staleSources.length" class="rounded-lg border border-amber-500/20 bg-amber-500/10 px-4 py-2 text-xs text-amber-700 dark:text-amber-300">
      {{ t("dashboard.staleData") }}: {{ staleSources.join(", ") }}
    </p>

    <div v-if="data" class="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
      <StatCard
        :label="t('dashboard.activeAccounts')"
        :value="data.accounts.enabled"
        :hint="`${data.accounts.total} ${t('dashboard.configured')}`"
      />
      <StatCard
        :label="t('dashboard.calls')"
        :value="data.calls.total"
        :hint="`${data.calls.error_rate}% ${t('dashboard.errorRate')}`"
      />
      <StatCard
        :label="t('dashboard.averageLatency')"
        :value="`${data.calls.average_duration_ms} ms`"
        :hint="`${data.calls.errors} ${t('dashboard.errors')}`"
      />
      <StatCard
        :label="t('dashboard.oauthSessions')"
        :value="data.oauth.active"
        :hint="`${data.oauth.tracked} ${t('dashboard.tracked')}`"
      />
      <StatCard
        :label="t('dashboard.analysisProjects')"
        :value="data.analysis.projects"
        :hint="`${data.analysis.active_sessions} ${t('dashboard.activeSessions')}`"
      />
      <StatCard
        :label="t('dashboard.workers')"
        :value="data.analysis.workers"
        :hint="`${data.analysis.running_workers} ${t('dashboard.running')}`"
      />
      <StatCard
        :label="t('dashboard.workspaceFree')"
        :value="formatBytes(data.workspace.free_bytes)"
        :hint="`${String(data.workspace.files ?? 0)} ${t('dashboard.files')}`"
      />
      <StatCard
        :label="t('dashboard.workspaceSize')"
        :value="formatBytes(data.workspace.size_bytes)"
        :hint="t('dashboard.cached')"
      />
    </div>

    <section v-if="data" class="rounded-xl border border-border bg-card p-5 shadow-sm">
      <h2 class="text-sm font-semibold">{{ t("dashboard.accountProviders") }}</h2>
      <div class="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <div
          v-for="(value, provider) in data.accounts.by_provider"
          :key="provider"
          class="rounded-lg bg-muted px-4 py-3"
        >
          <div class="text-xs uppercase text-muted-foreground">{{ provider }}</div>
          <div class="mt-1 text-xl font-semibold">{{ value }}</div>
        </div>
      </div>
    </section>
  </div>
</template>
