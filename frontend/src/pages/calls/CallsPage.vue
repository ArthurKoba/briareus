<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue"
import { Switch } from "ant-design-vue"
import { Activity, CheckCircle2, Circle, Radio, RefreshCw, Trash2, XCircle } from "lucide-vue-next"
import { useI18n } from "vue-i18n"

import { managementApi, type AccountRecord, type InvocationRecord } from "@/shared/api/management"
import { eventBus, type BusEvent } from "@/shared/events/bus"
import { formatDate } from "@/shared/lib/format"
import { tabWorkspace } from "@/shared/lib/tab-workspace"
import { notifications } from "@/shared/notifications/bus"
import AppDialog from "@/shared/ui/AppDialog.vue"
import Button from "@/shared/ui/Button.vue"
import DataTable from "@/shared/ui/DataTable.vue"
import JsonView from "@/shared/ui/JsonView.vue"
import PageHeader from "@/shared/ui/PageHeader.vue"

const { t } = useI18n()
const rows = ref<InvocationRecord[]>([])
const loading = ref(false)
const error = ref("")
const selected = ref<InvocationRecord | null>(null)
const limit = ref(250)
const pending = ref<InvocationRecord[]>([])
const accountsById = ref<Record<string, AccountRecord>>({})
const followLive = computed({ get: () => tabWorkspace.callsFollowLive, set: (value: boolean) => { tabWorkspace.callsFollowLive = value } })
let unsubscribe: undefined | (() => void)

const columns = computed(() => [
  { title: t("calls.time"), dataIndex: "occurred_at", key: "occurred_at", width: 180 },
  { title: t("calls.module"), dataIndex: "module", key: "module", width: 110 },
  { title: t("calls.tool"), dataIndex: "tool", key: "tool", width: 260 },
  { title: t("common.status"), dataIndex: "status", key: "status", width: 100 },
  { title: t("calls.duration"), dataIndex: "duration_ms", key: "duration_ms", width: 110 },
  { title: t("calls.account"), dataIndex: "account_id", key: "account_id", width: 170 },
  { title: "", key: "actions", width: 56, sortable: false, align: "right" as const },
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
  if (event.type === "snapshot") {
    const snapshot = event.data as { events?: InvocationRecord[] }
    for (const item of (snapshot.events ?? []).slice().reverse()) merge(item)
    return
  }
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
    const [calls, accounts] = await Promise.all([managementApi.calls(next), managementApi.accounts()])
    rows.value = calls.events
    accountsById.value = Object.fromEntries(accounts.accounts.map((account) => [account.id, account]))
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

function accountDisplay(item: InvocationRecord): string {
  if (!item.account_id) return "—"
  return accountsById.value[item.account_id]?.alias || item.account_id.slice(0, 12)
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
      clickable
      @row-click="inspect"
      @end-reached="loadMore"
    >
      <template #bodyCell="{ column, record, value }">
        <template v-if="column.key === 'occurred_at'">{{ formatDate(record.occurred_at) }}</template>
        <template v-else-if="column.key === 'status'">
          <span class="inline-flex items-center gap-1.5" :class="record.status === 'success' ? 'text-emerald-500' : 'text-destructive'">
            <CheckCircle2 v-if="record.status === 'success'" class="size-4" />
            <XCircle v-else class="size-4" />
            <span class="text-[11px]">{{ record.status }}</span>
          </span>
        </template>
        <template v-else-if="column.key === 'duration_ms'">{{ Number(record.duration_ms).toFixed(1) }} ms</template>
        <template v-else-if="column.key === 'account_id'">{{ accountDisplay(record as InvocationRecord) }}</template>
        <template v-else-if="column.key === 'actions'">
          <button data-row-action class="grid size-7 place-items-center rounded-md text-muted-foreground hover:bg-destructive/10 hover:text-destructive" :title="String(t('common.delete'))" @click="remove(record as InvocationRecord)">
            <Trash2 class="size-4" />
          </button>
        </template>
        <template v-else><span class="truncate">{{ value ?? "—" }}</span></template>
      </template>
    </DataTable>

    <AppDialog :open="Boolean(selected)" :title="t('calls.callTitle')" width="880px" :close-label="String(t('common.close'))" @close="selected = null">
      <div v-if="selected" class="space-y-5 text-sm">
        <div class="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <div class="rounded-lg bg-muted/50 p-3"><div class="text-[10px] uppercase text-muted-foreground">{{ t("calls.tool") }}</div><div class="mt-1 font-medium">{{ selected.tool }}</div></div>
          <div class="rounded-lg bg-muted/50 p-3"><div class="text-[10px] uppercase text-muted-foreground">{{ t("calls.module") }}</div><div class="mt-1">{{ selected.module }}</div></div>
          <div class="rounded-lg bg-muted/50 p-3"><div class="text-[10px] uppercase text-muted-foreground">{{ t("calls.account") }}</div><div class="mt-1">{{ accountDisplay(selected) }}</div></div>
          <div class="rounded-lg bg-muted/50 p-3"><div class="text-[10px] uppercase text-muted-foreground">{{ t("calls.duration") }}</div><div class="mt-1 tabular-nums">{{ Number(selected.duration_ms).toFixed(1) }} ms</div></div>
        </div>
        <div><div class="mb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">{{ t("calls.arguments") }}</div><JsonView :value="selected.arguments_json" /></div>
        <div v-if="selected.result_json"><div class="mb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">{{ t("calls.result") }}</div><JsonView :value="selected.result_json" /></div>
        <div v-if="selected.error_message || selected.error_type"><div class="mb-1 text-xs font-semibold uppercase tracking-wide text-destructive">{{ t("calls.error") }}</div><JsonView :value="selected.error_message || selected.error_type" /></div>
        <div class="text-[11px] text-muted-foreground">{{ t("calls.requestId") }}: <span class="font-mono">{{ selected.request_id || "—" }}</span></div>
      </div>
    </AppDialog>
  </div>
</template>
