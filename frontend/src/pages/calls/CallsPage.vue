<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue"
import { Modal, Switch, Tag } from "ant-design-vue"
import { Activity, Circle, Radio, RefreshCw, Trash2 } from "lucide-vue-next"
import { useI18n } from "vue-i18n"

import { managementApi, type InvocationRecord } from "@/shared/api/management"
import { eventBus, type BusEvent } from "@/shared/events/bus"
import { formatDate } from "@/shared/lib/format"
import { tabWorkspace } from "@/shared/lib/tab-workspace"
import { notifications } from "@/shared/notifications/bus"
import Button from "@/shared/ui/Button.vue"
import DataTable from "@/shared/ui/DataTable.vue"
import PageHeader from "@/shared/ui/PageHeader.vue"

const { t } = useI18n()
const rows = ref<InvocationRecord[]>([])
const loading = ref(false)
const error = ref("")
const selected = ref<InvocationRecord | null>(null)
const limit = ref(250)
const pending = ref<InvocationRecord[]>([])
const followLive = computed({ get: () => tabWorkspace.callsFollowLive, set: (value: boolean) => { tabWorkspace.callsFollowLive = value } })
let unsubscribe: undefined | (() => void)

const columns = computed(() => [
  { title: t("calls.time"), dataIndex: "occurred_at", key: "occurred_at", width: 180 },
  { title: t("calls.module"), dataIndex: "module", key: "module", width: 110 },
  { title: t("calls.tool"), dataIndex: "tool", key: "tool", width: 260 },
  { title: t("common.status"), dataIndex: "status", key: "status", width: 100 },
  { title: t("calls.duration"), dataIndex: "duration_ms", key: "duration_ms", width: 110 },
  { title: t("common.provider"), dataIndex: "provider", key: "provider", width: 120 },
  { title: t("common.actions"), key: "actions", width: 130 },
])

const errorCount = computed(() => rows.value.filter((item) => item.status === "error").length)
const live = computed(() => eventBus.state.status === "connected")

function merge(item: InvocationRecord): void {
  const index = rows.value.findIndex((row) => row.id === item.id)
  if (index >= 0) rows.value.splice(index, 1, item)
  else rows.value.unshift(item)
  if (rows.value.length > 1000) rows.value.length = 1000
}

function handle(event: BusEvent): void {
  if (event.type !== "item") return
  const item = event.data as InvocationRecord
  if (followLive.value) merge(item)
  else if (!pending.value.some((row) => row.id === item.id)) pending.value.unshift(item)
}

function applyPending(): void {
  for (const item of pending.value.slice().reverse()) merge(item)
  pending.value = []
  followLive.value = true
}

async function load(next = limit.value): Promise<void> {
  loading.value = true
  error.value = ""
  try {
    limit.value = next
    rows.value = (await managementApi.calls(next)).events
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : "Unable to load calls"
  } finally {
    loading.value = false
  }
}

async function loadMore(): Promise<void> {
  if (loading.value || limit.value >= 1000 || rows.value.length < limit.value) return
  await load(Math.min(1000, limit.value + 250))
}

function inspect(item: unknown): void {
  selected.value = item as InvocationRecord
}

async function clearAll(): Promise<void> {
  if (!window.confirm(String(t("calls.clearConfirm")))) return
  const result = await managementApi.clearCalls()
  rows.value = []
  pending.value = []
  notifications.success(String(t("notifications.deleted")), `${result.deleted} ${t("nav.calls")}`)
}

async function remove(item: InvocationRecord): Promise<void> {
  await managementApi.deleteCall(item.id)
  rows.value = rows.value.filter((row) => row.id !== item.id)
  notifications.success(String(t("notifications.deleted")))
}

onMounted(async () => {
  await load()
  unsubscribe = eventBus.subscribe("mcp.calls", handle)
})
onBeforeUnmount(() => unsubscribe?.())
</script>

<template>
  <div class="space-y-6">
    <PageHeader :title="t('nav.calls')" :description="t('calls.description')">
      <details class="group relative">
        <summary class="flex size-8 cursor-pointer list-none items-center justify-center rounded-md border border-border bg-background text-muted-foreground hover:bg-accent hover:text-foreground [&::-webkit-details-marker]:hidden" :title="String(t('calls.liveControl'))">
          <Radio v-if="live" class="size-4 text-emerald-500" />
          <Activity v-else class="size-4" :class="eventBus.state.status === 'reconnecting' ? 'animate-pulse text-amber-500' : ''" />
        </summary>
        <div class="absolute right-0 top-10 z-40 w-72 rounded-xl border border-border bg-popover p-3 shadow-xl">
          <div class="flex items-start justify-between gap-3">
            <div><div class="text-sm font-semibold">{{ t("calls.liveControl") }}</div><div class="mt-0.5 text-[11px] text-muted-foreground">{{ t("calls.liveControlHint") }}</div></div>
            <span class="inline-flex items-center gap-1 text-[10px] uppercase text-muted-foreground"><Circle class="size-2.5 fill-current" :class="live ? 'text-emerald-500' : 'text-muted-foreground'" />{{ eventBus.state.status }}</span>
          </div>
          <label class="mt-3 flex items-center justify-between gap-3 rounded-lg border border-border/70 px-3 py-2.5 text-xs">
            <span>{{ t("calls.follow") }}</span>
            <Switch v-model:checked="followLive" size="small" />
          </label>
          <div class="mt-2 flex items-center justify-between rounded-lg bg-muted/50 px-3 py-2 text-xs"><span class="text-muted-foreground">{{ t("realtime.lastEvent") }}</span><span>{{ eventBus.state.lastEventAt ? formatDate(eventBus.state.lastEventAt) : "—" }}</span></div>
          <Button v-if="pending.length" class="mt-2 w-full" size="sm" @click="applyPending">{{ pending.length }} {{ t("calls.new") }}</Button>
        </div>
      </details>
      <Button variant="outline" size="sm" @click="load()">
        <RefreshCw class="mr-2 size-4" />{{ t("common.refresh") }}
      </Button>
      <Button variant="destructive" size="sm" @click="clearAll">
        <Trash2 class="mr-2 size-4" />{{ t("calls.clear") }}
      </Button>
    </PageHeader>

    <div class="flex gap-3 text-xs text-muted-foreground">
      <span>{{ rows.length }} {{ t("calls.loaded") }}</span>
      <span>{{ errorCount }} {{ t("calls.errors") }}</span>
      <span>{{ t("calls.limit") }} {{ limit }}</span>
    </div>
    <p v-if="error" class="text-sm text-destructive">{{ error }}</p>

    <DataTable
      :columns="columns"
      :data-source="rows"
      :loading="loading"
      :pagination="false"
      virtual
      :scroll-y="620"
      @end-reached="loadMore"
    >
      <template #bodyCell="{ column, record, value }">
        <template v-if="column.key === 'occurred_at'">{{ formatDate(record.occurred_at) }}</template>
        <template v-else-if="column.key === 'status'">
          <Tag :color="record.status === 'success' ? 'green' : 'red'">{{ record.status }}</Tag>
        </template>
        <template v-else-if="column.key === 'duration_ms'">{{ Number(record.duration_ms).toFixed(1) }} ms</template>
        <template v-else-if="column.key === 'actions'">
          <div class="flex gap-1">
            <Button variant="ghost" size="sm" @click="inspect(record)">{{ t("calls.inspect") }}</Button>
            <Button variant="ghost" size="sm" @click="remove(record as InvocationRecord)">{{ t("common.delete") }}</Button>
          </div>
        </template>
        <template v-else><span class="truncate">{{ value ?? "—" }}</span></template>
      </template>
    </DataTable>

    <Modal :open="Boolean(selected)" :title="t('calls.callTitle')" :footer="null" width="860px" @cancel="selected = null">
      <div v-if="selected" class="space-y-4 text-sm">
        <div class="grid gap-3 sm:grid-cols-2">
          <div>
            <span class="text-muted-foreground">{{ t("calls.tool") }}</span>
            <div class="font-medium">{{ selected.tool }}</div>
          </div>
          <div>
            <span class="text-muted-foreground">{{ t("calls.requestId") }}</span>
            <div class="break-all font-mono text-xs">{{ selected.request_id || "—" }}</div>
          </div>
        </div>
        <div
          v-for="[label, value] in [
            [t('calls.arguments'), selected.arguments_json],
            [t('calls.result'), selected.result_json],
            [t('calls.error'), selected.error_message],
          ]"
          :key="String(label)"
        >
          <div class="mb-1 text-xs font-medium uppercase text-muted-foreground">{{ label }}</div>
          <pre class="max-h-64 overflow-auto rounded-lg bg-muted p-3 text-xs whitespace-pre-wrap">{{ value || "—" }}</pre>
        </div>
      </div>
    </Modal>
  </div>
</template>
