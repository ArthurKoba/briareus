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

function accept(event: BusEvent): void {
  if (!data.value || event.type !== "snapshot") return
  const next = event.data as Partial<DashboardState> & { analysis?: unknown }
  const analysis = next.analysis
  let analysisSummary = data.value.analysis
  if (analysis && typeof analysis === "object") {
    const raw = analysis as Record<string, unknown>
    if (typeof raw.projects === "number") analysisSummary = raw as unknown as DashboardState["analysis"]
    else {
      const projects = Array.isArray(raw.projects) ? raw.projects as Array<Record<string, unknown>> : []
      const workers = Array.isArray(raw.workers) ? raw.workers as Array<Record<string, unknown>> : []
      if (projects.length || workers.length) analysisSummary = {
        projects: projects.length,
        active_sessions: projects.filter((item) => item.session === "active").length,
        workers: workers.length,
        running_workers: workers.filter((item) => Boolean(item.running)).length,
      }
    }
  }
  data.value = {
    ...data.value,
    ...(next.accounts ? { accounts: next.accounts } : {}),
    ...(next.calls ? { calls: next.calls } : {}),
    ...(next.oauth ? { oauth: next.oauth } : {}),
    ...(next.workspace ? { workspace: next.workspace } : {}),
    analysis: analysisSummary,
  }
  synced.value = liveTransport.value
}

async function load(): Promise<void> {
  loading.value = true
  error.value = ""
  try {
    const snapshot = await managementApi.dashboard()
    data.value = snapshot
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : "Unable to load dashboard"
  } finally {
    loading.value = false
  }
}

watch(liveTransport, (live) => { if (!live) synced.value = false })

onMounted(async () => {
  await load()
  unsubscribe = eventBus.subscribe("system.metrics", accept)
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
