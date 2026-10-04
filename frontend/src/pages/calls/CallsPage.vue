<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue"
import { CheckCircle2, Trash2, XCircle } from "lucide-vue-next"
import { useI18n } from "vue-i18n"
import { Select, Switch } from "ant-design-vue"

import { managementApi, type AccountRecord, type InvocationRecord } from "@/shared/api/management"
import { formatDate } from "@/shared/lib/format"
import { notifications } from "@/shared/notifications/bus"
import AppDialog from "@/shared/ui/AppDialog.vue"
import Button from "@/shared/ui/Button.vue"
import JsonView from "@/shared/ui/JsonView.vue"
import { accountStore } from "@/features/accounts/model/account-store"
import { callStore, type CallViewMode } from "./model/call-store"
import PageHeader from "@/shared/ui/PageHeader.vue"
import RefreshAction from "@/shared/ui/RefreshAction.vue"
import { RelativeTime } from "@/shared/ui/relative-time"
import { PaginatedTable, VirtualInfiniteTable, type DataTableColumn } from "@/shared/ui/table"

const { t } = useI18n()
const rows = computed(() => callStore.state.mode === "pagination" ? callStore.state.pageRows : callStore.state.rows)
const loading = computed(() => callStore.state.mode === "pagination" ? callStore.state.pageLoading : callStore.state.loading)
const error = computed(() => callStore.state.error)
const selected = ref<InvocationRecord | null>(null)
const pending = computed(() => callStore.state.pending)
const accountsById = computed<Record<string, AccountRecord>>(() => Object.fromEntries(accountStore.state.accounts.map(account => [account.id, account])))
const searchDraft = ref(callStore.state.filters.search)

const modeOptions = computed(() => [
  { label: t("calls.infiniteMode"), value: "infinite" },
  { label: t("calls.paginationMode"), value: "pagination" },
])
const moduleOptions = computed(() => [{ label: t("calls.allModules"), value: "" }, ...[...new Set(callStore.state.recent.map(item => item.module))].sort().map(value => ({ label: value, value }))])
const toolOptions = computed(() => [{ label: t("calls.allTools"), value: "" }, ...[...new Set(callStore.state.recent.map(item => item.tool))].sort().map(value => ({ label: value, value }))])
const providerOptions = computed(() => [{ label: t("calls.allProviders"), value: "" }, ...[...new Set(callStore.state.recent.map(item => item.provider).filter(Boolean))].sort().map(value => ({ label: value, value }))])
const accountOptions = computed(() => [{ label: t("calls.allAccounts"), value: "" }, ...accountStore.state.accounts.map(account => ({ label: account.alias, value: account.id }))])
const statusOptions = computed(() => [
  { label: t("calls.allStatuses"), value: "" },
  { label: "success", value: "success" },
  { label: "error", value: "error" },
])

const columns = computed<DataTableColumn[]>(() => [
  { title: t("calls.time"), dataIndex: "occurred_at", key: "occurred_at", width: 180, sortable: false },
  { title: t("calls.module"), dataIndex: "module", key: "module", width: 110, sortable: false },
  { title: t("calls.tool"), dataIndex: "tool", key: "tool", width: 260, sortable: false },
  { title: t("common.status"), dataIndex: "status", key: "status", width: 100, sortable: false },
  { title: t("calls.duration"), dataIndex: "duration_ms", key: "duration_ms", width: 110, sortable: false },
  { title: t("calls.account"), dataIndex: "account_id", key: "account_id", width: 170, sortable: false },
  { title: "", key: "actions", width: 56, sortable: false, align: "right" as const },
])


function applyPending(): void { callStore.applyPending() }
async function load(): Promise<void> {
  try { await callStore.refresh() } catch { /* store owns local error */ }
}
async function changeMode(value: string): Promise<void> { await callStore.setMode(value as CallViewMode) }
async function updateFilter(key: "module" | "tool" | "provider" | "account_id" | "status", value: string): Promise<void> {
  await callStore.setFilters({ [key]: value })
}
async function applySearch(): Promise<void> { await callStore.setFilters({ search: searchDraft.value.trim() }) }

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
  callStore.clear()
  notifications.success(String(t("notifications.deleted")), `${result.deleted} ${t("nav.calls")}`)
}

async function remove(item: InvocationRecord): Promise<void> {
  await managementApi.deleteCall(item.id)
  callStore.remove(item.id)
  notifications.success(String(t("notifications.deleted")))
}


onMounted(() => {
  callStore.setFollowingLive(true)
  if (!callStore.state.hydrated) void callStore.ensure().catch(() => undefined)
  if (callStore.state.mode === "pagination" && !callStore.state.pageRows.length) void callStore.setPage(1).catch(() => undefined)
})
onBeforeUnmount(() => callStore.leaveView())
</script>

<template>
  <div class="space-y-5">
    <PageHeader :title="t('nav.calls')" :description="t('calls.description')">
      <RefreshAction :synced="callStore.state.synced" :loading="loading" @refresh="load" />
      <Button v-if="callStore.state.mode === 'infinite' && pending.length" size="sm" @click="applyPending">{{ pending.length }} {{ t("calls.new") }}</Button>
      <Button variant="destructive" size="sm" @click="clearAll"><Trash2 class="mr-2 size-4" />{{ t("calls.clear") }}</Button>
    </PageHeader>

    <div class="flex flex-wrap items-center gap-2 rounded-xl border border-border/70 bg-card p-3">
      <Select :value="callStore.state.mode" :options="modeOptions" class="w-44" @change="changeMode(String($event))" />
      <input v-model="searchDraft" class="field h-8 min-w-52 flex-1" :placeholder="String(t('calls.search'))" @keyup.enter="applySearch" />
      <Select :value="callStore.state.filters.module" :options="moduleOptions" class="w-40" @change="updateFilter('module', String($event))" />
      <Select :value="callStore.state.filters.tool" :options="toolOptions" class="w-48" @change="updateFilter('tool', String($event))" />
      <Select :value="callStore.state.filters.provider" :options="providerOptions" class="w-36" @change="updateFilter('provider', String($event))" />
      <Select :value="callStore.state.filters.account_id" :options="accountOptions" class="w-44" @change="updateFilter('account_id', String($event))" />
      <Select :value="callStore.state.filters.status" :options="statusOptions" class="w-36" @change="updateFilter('status', String($event))" />
      <label class="ml-auto inline-flex items-center gap-2 text-xs text-muted-foreground"><Switch :checked="callStore.state.relativeTime" size="small" @change="callStore.setRelativeTime(Boolean($event))" />{{ t("calls.relativeTime") }}</label>
    </div>

    <p v-if="error" class="text-sm text-destructive">{{ error }}</p>

    <PaginatedTable
      v-if="callStore.state.mode === 'pagination'"
      :columns="columns"
      :data-source="rows"
      :loading="loading"
      :page="callStore.state.page"
      :page-size="callStore.state.pageSize"
      :total-rows="callStore.state.pageTotal"
      :row-key="(record: any) => record.id"
      clickable
      @update:page="callStore.setPage"
      @update:page-size="callStore.setPageSize"
      @row-click="inspect"
    >
      <template #bodyCell="{ column, record, value }">
        <template v-if="column.key === 'occurred_at'">
          <RelativeTime v-if="callStore.state.relativeTime" :value="record.occurred_at" :interval-ms="2000" />
          <template v-else>{{ formatDate(record.occurred_at) }}</template>
        </template>
        <template v-else-if="column.key === 'status'">
          <span class="inline-flex items-center gap-1.5" :class="record.status === 'success' ? 'text-emerald-500' : 'text-destructive'">
            <CheckCircle2 v-if="record.status === 'success'" class="size-4" /><XCircle v-else class="size-4" /><span class="text-[11px]">{{ record.status }}</span>
          </span>
        </template>
        <template v-else-if="column.key === 'duration_ms'"><span class="tabular-nums">{{ Number(record.duration_ms).toFixed(1) }} ms</span></template>
        <template v-else-if="column.key === 'account_id'">{{ accountDisplay(record as InvocationRecord) }}</template>
        <template v-else-if="column.key === 'actions'"><button data-row-action class="grid size-7 place-items-center rounded-md text-muted-foreground hover:bg-destructive/10 hover:text-destructive" :title="String(t('common.delete'))" @click.stop="remove(record as InvocationRecord)"><Trash2 class="size-4" /></button></template>
        <template v-else><span class="truncate">{{ value ?? "—" }}</span></template>
      </template>
    </PaginatedTable>

    <VirtualInfiniteTable
      v-else
      :columns="columns"
      :data-source="rows"
      :loading="loading"
      :loading-more="callStore.state.loadingMore"
      :has-more="callStore.state.hasMore"
      :row-key="(record: any) => record.id"
      :scroll-y="650"
      clickable
      @end-reached="callStore.loadMore"
      @row-click="inspect"
      @scroll-position="callStore.setFollowingLive"
    >
      <template #bodyCell="{ column, record, value }">
        <template v-if="column.key === 'occurred_at'">
          <RelativeTime v-if="callStore.state.relativeTime" :value="record.occurred_at" :interval-ms="2000" />
          <template v-else>{{ formatDate(record.occurred_at) }}</template>
        </template>
        <template v-else-if="column.key === 'status'">
          <span class="inline-flex items-center gap-1.5" :class="record.status === 'success' ? 'text-emerald-500' : 'text-destructive'">
            <CheckCircle2 v-if="record.status === 'success'" class="size-4" /><XCircle v-else class="size-4" /><span class="text-[11px]">{{ record.status }}</span>
          </span>
        </template>
        <template v-else-if="column.key === 'duration_ms'"><span class="tabular-nums">{{ Number(record.duration_ms).toFixed(1) }} ms</span></template>
        <template v-else-if="column.key === 'account_id'">{{ accountDisplay(record as InvocationRecord) }}</template>
        <template v-else-if="column.key === 'actions'"><button data-row-action class="grid size-7 place-items-center rounded-md text-muted-foreground hover:bg-destructive/10 hover:text-destructive" :title="String(t('common.delete'))" @click.stop="remove(record as InvocationRecord)"><Trash2 class="size-4" /></button></template>
        <template v-else><span class="truncate">{{ value ?? "—" }}</span></template>
      </template>
    </VirtualInfiniteTable>

    <AppDialog :open="Boolean(selected)" :title="selected ? `${t('calls.callTitle')} · ${selected.request_id || selected.id}` : t('calls.callTitle')" width="880px" :close-label="String(t('common.close'))" @close="selected = null">
      <div v-if="selected" class="space-y-5 text-sm">
        <div class="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <div class="rounded-lg bg-muted/50 p-3"><div class="text-[10px] uppercase text-muted-foreground">{{ t("calls.module") }}</div><div class="mt-1 font-medium">{{ selected.module }}</div></div>
          <div class="rounded-lg bg-muted/50 p-3"><div class="text-[10px] uppercase text-muted-foreground">{{ t("calls.tool") }}</div><div class="mt-1">{{ selected.tool }}</div></div>
          <div class="rounded-lg bg-muted/50 p-3"><div class="text-[10px] uppercase text-muted-foreground">{{ t("calls.duration") }}</div><div class="mt-1 tabular-nums">{{ Number(selected.duration_ms).toFixed(1) }} ms</div></div>
          <div class="rounded-lg bg-muted/50 p-3"><div class="text-[10px] uppercase text-muted-foreground">{{ t("calls.account") }}</div><div class="mt-1">{{ accountDisplay(selected) }}</div></div>
        </div>
        <div><div class="mb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">{{ t("calls.arguments") }}</div><JsonView :value="selected.arguments_json" /></div>
        <div v-if="selected.result_json"><div class="mb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">{{ t("calls.result") }}</div><JsonView :value="selected.result_json" /></div>
        <div v-if="selected.error_message || selected.error_type"><div class="mb-1 text-xs font-semibold uppercase tracking-wide text-destructive">{{ t("calls.error") }}</div><JsonView :value="selected.error_message || selected.error_type" /></div>
      </div>
    </AppDialog>
  </div>
</template>
