<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue"
import { useI18n } from "vue-i18n"
import { CheckCircle2, XCircle } from "lucide-vue-next"

import { adminApi, type DashboardState } from "@/shared/api/admin"
import { eventBus, type BusEvent } from "@/shared/events/bus"
import { formatBytes } from "@/shared/lib/format"
import { callStore } from "@/pages/calls/model/call-store"
import { RelativeTime } from "@/shared/ui/relative-time"
import { VirtualInfiniteTable, type DataTableColumn } from "@/shared/ui/table"
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
const recentCalls = computed(() => callStore.state.recent.slice(0, 10))
const recentCallColumns = computed<DataTableColumn[]>(() => [
  { title: t("calls.time"), dataIndex: "occurred_at", key: "occurred_at", width: 128, sortable: false },
  { title: t("calls.module"), dataIndex: "module", key: "module", width: 120, sortable: false },
  { title: t("calls.tool"), dataIndex: "tool", key: "tool", sortable: false },
  { title: t("common.status"), dataIndex: "status", key: "status", width: 100, sortable: false },
  { title: t("calls.duration"), dataIndex: "duration_ms", key: "duration_ms", width: 105, sortable: false, align: "right" },
])

function openCalls(): void { location.hash = "calls" }

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
    const snapshot = await adminApi.dashboard()
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

    <div v-if="data" class="space-y-6">
      <section class="space-y-3">
        <div>
          <h2 class="text-sm font-semibold">{{ t("dashboard.mcpGroup") }}</h2>
          <p class="mt-0.5 text-xs text-muted-foreground">{{ t("dashboard.mcpGroupHint") }}</p>
        </div>
        <div class="grid gap-4 md:grid-cols-2">
          <StatCard
            :label="t('dashboard.calls')"
            :value="data.calls.total"
            :hint="`${data.calls.errors} ${t('dashboard.errors')} · ${data.calls.error_rate}%`"
          />
          <StatCard
            :label="t('dashboard.averageLatency')"
            :value="`${data.calls.average_duration_ms} ms`"
            :hint="t('dashboard.averageLatencyHint')"
          />
        </div>
      </section>

      <section class="space-y-3">
        <div>
          <h2 class="text-sm font-semibold">{{ t("dashboard.integrationsGroup") }}</h2>
          <p class="mt-0.5 text-xs text-muted-foreground">{{ t("dashboard.integrationsGroupHint") }}</p>
        </div>
        <div class="grid gap-4 md:grid-cols-2">
          <StatCard
            :label="t('dashboard.enabledIntegrations')"
            :value="data.accounts.enabled"
            :hint="`${data.accounts.total} ${t('dashboard.configured')}`"
          >
            <template #footer>
              <div class="flex flex-wrap gap-2">
                <span
                  v-for="(value, provider) in data.accounts.by_provider"
                  :key="provider"
                  class="inline-flex items-center gap-1.5 rounded-md bg-muted px-2 py-1 text-[11px]"
                >
                  <span class="uppercase text-muted-foreground">{{ provider }}</span>
                  <b class="tabular-nums text-foreground">{{ value }}</b>
                </span>
              </div>
            </template>
          </StatCard>
          <StatCard
            :label="t('dashboard.oauthClientSessions')"
            :value="data.oauth.active"
            :hint="`${data.oauth.tracked} ${t('dashboard.oauthTracked')}`"
          />
        </div>
      </section>

      <section class="space-y-3">
        <div>
          <h2 class="text-sm font-semibold">Ghidra</h2>
          <p class="mt-0.5 text-xs text-muted-foreground">{{ t("dashboard.ghidraGroupHint") }}</p>
        </div>
        <div class="grid gap-4 md:grid-cols-2">
          <StatCard
            :label="t('dashboard.ghidraProjects')"
            :value="data.analysis.projects"
            :hint="`${data.analysis.active_sessions} ${t('dashboard.ghidraActiveSessions')}`"
          />
          <StatCard
            :label="t('dashboard.ghidraWorkers')"
            :value="data.analysis.workers"
            :hint="`${data.analysis.running_workers} ${t('dashboard.ghidraRunningWorkers')}`"
          />
        </div>
      </section>

      <section class="space-y-3">
        <h2 class="text-xs font-semibold uppercase tracking-wide text-muted-foreground">{{ t("dashboard.workspaceGroup") }}</h2>
        <div class="grid gap-4 md:grid-cols-2">
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
      </section>
    </div>

    <section class="overflow-hidden rounded-xl border border-border bg-card shadow-sm">
      <div class="border-b border-border/70 px-4 py-3">
        <h2 class="text-sm font-semibold">{{ t("nav.calls") }}</h2>
      </div>
      <VirtualInfiniteTable
        :columns="recentCallColumns"
        :data-source="recentCalls"
        :loading="callStore.state.recentLoading"
        :has-more="false"
        :framed="false"
        :row-key="(record: any) => record.id"
        :scroll-y="360"
      >
        <template #bodyCell="{ column, record, value }">
          <template v-if="column.key === 'occurred_at'"><RelativeTime :value="record.occurred_at" :interval-ms="2000" /></template>
          <template v-else-if="column.key === 'status'">
            <span class="inline-flex items-center gap-1.5" :class="record.status === 'success' ? 'text-emerald-500' : 'text-destructive'">
              <CheckCircle2 v-if="record.status === 'success'" class="size-3.5" /><XCircle v-else class="size-3.5" />
              <span>{{ record.status }}</span>
            </span>
          </template>
          <template v-else-if="column.key === 'duration_ms'"><span class="tabular-nums">{{ Number(record.duration_ms).toFixed(1) }} ms</span></template>
          <template v-else><span class="truncate">{{ value ?? "—" }}</span></template>
        </template>
      </VirtualInfiniteTable>
      <button type="button" class="flex w-full items-center justify-center border-t border-border/70 px-4 py-3 text-sm font-medium text-primary hover:bg-accent/50" @click="openCalls">
        {{ t("nav.calls") }} →
      </button>
    </section>
  </div>
</template>
