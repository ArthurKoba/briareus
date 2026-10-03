<script setup lang="ts">
import { computed, ref } from "vue"
import { Switch } from "ant-design-vue"
import { Activity, CheckCircle2, Clock3, DatabaseZap, Info, Send, TriangleAlert, XCircle } from "lucide-vue-next"
import { useI18n } from "vue-i18n"

import { runtimeConfig } from "@/shared/config/runtime"
import { frontendTelemetry, type FrontendTelemetryEvent } from "@/shared/telemetry/client"
import { formatDate } from "@/shared/lib/format"
import { uiPreferences } from "@/shared/lib/preferences"
import AppDialog from "@/shared/ui/AppDialog.vue"
import DataTable from "@/shared/ui/DataTable.vue"
import PageHeader from "@/shared/ui/PageHeader.vue"
import StatCard from "@/shared/ui/StatCard.vue"

const { t } = useI18n()
const selected = ref<FrontendTelemetryEvent | null>(null)
const events = computed(() => frontendTelemetry.events.slice(0, 500))
const errorCount = computed(() => events.value.filter((event) => event.level === "error").length)
const lastEvent = computed(() => events.value[0]?.occurredAt ?? "")

const columns = computed(() => [
  { title: t("telemetry.time"), dataIndex: "occurredAt", key: "occurredAt", width: 180 },
  { title: t("telemetry.event"), dataIndex: "name", key: "name", width: 220 },
  { title: t("telemetry.route"), dataIndex: "route", key: "route", width: 210 },
  { title: t("telemetry.duration"), dataIndex: "durationMs", key: "durationMs", width: 120, align: "right" as const },
  { title: t("telemetry.level"), dataIndex: "level", key: "level", width: 100 },
  { title: "", key: "actions", width: 90, sortable: false },
])

function inspect(record: unknown): void {
  selected.value = record as FrontendTelemetryEvent
}
</script>

<template>
  <div class="space-y-5">
    <PageHeader :title="t('telemetry.title')" :description="runtimeConfig.telemetry.enabled ? runtimeConfig.telemetry.endpoint : t('telemetry.pending')">
      <label class="inline-flex items-center gap-2 text-xs text-muted-foreground"><span>{{ t("telemetry.collection") }}</span><Switch v-model:checked="uiPreferences.telemetryEnabled.value" size="small" /></label>
    </PageHeader>

    <div v-if="!runtimeConfig.telemetry.enabled" class="rounded-xl border border-amber-500/25 bg-amber-500/10 px-4 py-3 text-sm text-amber-800 dark:text-amber-300">{{ t("telemetry.deliveryDisabledReason") }}</div>

    <div class="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
      <StatCard
        :label="t('telemetry.collection')"
        :value="uiPreferences.telemetryEnabled.value ? t('common.enabled') : t('common.disabled')"
        :hint="t('telemetry.localBuffer')"
      />
      <StatCard :label="t('telemetry.delivery')" :value="runtimeConfig.telemetry.enabled ? t('common.enabled') : t('common.disabled')" :hint="runtimeConfig.telemetry.endpoint" />
      <StatCard :label="t('telemetry.event')" :value="events.length" :hint="t('telemetry.localBuffer')" />
      <StatCard :label="t('calls.errors')" :value="errorCount" :hint="lastEvent ? formatDate(lastEvent) : '—'" />
      <StatCard :label="t('telemetry.queue')" :value="frontendTelemetry.pendingCount" :hint="t('telemetry.batchHint')" />
    </div>

    <div class="grid gap-3 md:grid-cols-3">
      <div class="rounded-xl border border-border/70 bg-card p-3 text-xs">
        <div class="flex items-center gap-2 font-medium"><DatabaseZap class="size-4 text-muted-foreground" />{{ t("telemetry.bufferTitle") }}</div>
        <p class="mt-1 text-muted-foreground">{{ t("telemetry.bufferHint") }}</p>
      </div>
      <div class="rounded-xl border border-border/70 bg-card p-3 text-xs">
        <div class="flex items-center gap-2 font-medium"><Send class="size-4 text-muted-foreground" />{{ t("telemetry.deliveryTitle") }}</div>
        <p class="mt-1 text-muted-foreground">{{ t("telemetry.deliveryHint") }}</p>
      </div>
      <div class="rounded-xl border border-border/70 bg-card p-3 text-xs">
        <div class="flex items-center gap-2 font-medium"><Clock3 class="size-4 text-muted-foreground" />{{ t("telemetry.detailTitle") }}</div>
        <p class="mt-1 text-muted-foreground">{{ t("telemetry.detailHint") }}</p>
      </div>
    </div>

    <DataTable
      :columns="columns"
      :data-source="events"
      row-key="id"
      :pagination="false"
      virtual
      :scroll-y="620"
      clickable
      @row-click="inspect"
    >
      <template #bodyCell="{ column, record, value }">
        <template v-if="column.key === 'occurredAt'">{{ formatDate(record.occurredAt) }}</template>
        <template v-else-if="column.key === 'durationMs'">
          <span class="w-full text-right tabular-nums">{{ record.durationMs === undefined ? "—" : `${Number(record.durationMs).toFixed(1)} ms` }}</span>
        </template>
        <template v-else-if="column.key === 'level'">
          <span class="inline-flex items-center gap-1.5" :class="record.level === 'error' ? 'text-destructive' : record.level === 'warn' ? 'text-amber-500' : record.level === 'info' ? 'text-sky-500' : 'text-muted-foreground'">
            <XCircle v-if="record.level === 'error'" class="size-4" />
            <TriangleAlert v-else-if="record.level === 'warn'" class="size-4" />
            <Info v-else-if="record.level === 'info'" class="size-4" />
            <CheckCircle2 v-else class="size-4" />
            <span class="text-[11px]">{{ record.level }}</span>
          </span>
        </template>
        <template v-else-if="column.key === 'actions'">
          <button class="text-xs font-medium text-primary hover:underline" @click="inspect(record)">{{ t("common.open") }}</button>
        </template>
        <template v-else><span class="truncate">{{ value ?? "—" }}</span></template>
      </template>
    </DataTable>

    <AppDialog :open="Boolean(selected)" :title="selected?.name || t('telemetry.detailTitle')" width="840px" :close-label="String(t('common.close'))" @close="selected = null">
      <div v-if="selected" class="space-y-4 text-sm">
        <div class="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <div class="rounded-lg bg-muted/60 p-3"><div class="text-[10px] uppercase text-muted-foreground">{{ t("telemetry.time") }}</div><div class="mt-1 text-xs">{{ formatDate(selected.occurredAt) }}</div></div>
          <div class="rounded-lg bg-muted/60 p-3"><div class="text-[10px] uppercase text-muted-foreground">{{ t("telemetry.level") }}</div><div class="mt-1 text-xs">{{ selected.level }}</div></div>
          <div class="rounded-lg bg-muted/60 p-3"><div class="text-[10px] uppercase text-muted-foreground">{{ t("telemetry.route") }}</div><div class="mt-1 break-all font-mono text-xs">{{ selected.route }}</div></div>
          <div class="rounded-lg bg-muted/60 p-3"><div class="text-[10px] uppercase text-muted-foreground">{{ t("telemetry.duration") }}</div><div class="mt-1 text-xs">{{ selected.durationMs === undefined ? "—" : `${selected.durationMs.toFixed(1)} ms` }}</div></div>
        </div>
        <div><div class="mb-1 flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground"><Activity class="size-3.5" />{{ t("telemetry.attributes") }}</div><pre class="max-h-[50vh] overflow-auto rounded-lg border border-border/60 bg-muted/60 p-3 text-xs whitespace-pre-wrap">{{ JSON.stringify(selected.attributes, null, 2) }}</pre></div>
      </div>
    </AppDialog>
  </div>
</template>
