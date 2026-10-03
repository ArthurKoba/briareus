<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue"
import { Modal, Tag } from "ant-design-vue"
import { Radio, RefreshCw, Trash2 } from "lucide-vue-next"
import { managementApi, type InvocationRecord } from "@/shared/api/management"
import { formatDate } from "@/shared/lib/format"
import Button from "@/shared/ui/Button.vue"
import DataTable from "@/shared/ui/DataTable.vue"
import PageHeader from "@/shared/ui/PageHeader.vue"

const rows = ref<InvocationRecord[]>([])
const loading = ref(false)
const streamLive = ref(false)
const error = ref("")
const selected = ref<InvocationRecord | null>(null)
let source: EventSource | null = null
const columns = [
  { title: "Time", dataIndex: "occurred_at", key: "occurred_at", width: 180 },
  { title: "Module", dataIndex: "module", key: "module", width: 110 },
  { title: "Tool", dataIndex: "tool", key: "tool" },
  { title: "Status", dataIndex: "status", key: "status", width: 100 },
  { title: "Duration", dataIndex: "duration_ms", key: "duration_ms", width: 110 },
  { title: "Provider", dataIndex: "provider", key: "provider", width: 120 },
  { title: "Actions", key: "actions", width: 120 },
]
const errorCount = computed(() => rows.value.filter(item => item.status === "error").length)
async function load() { loading.value = true; error.value = ""; try { rows.value = (await managementApi.calls()).events } catch (e) { error.value = e instanceof Error ? e.message : "Unable to load calls" } finally { loading.value = false } }
function connect() { source?.close(); source = new EventSource(managementApi.callsStreamUrl); source.onopen = () => streamLive.value = true; source.onerror = () => streamLive.value = false; source.onmessage = event => { const item = JSON.parse(event.data) as InvocationRecord; const existing = rows.value.findIndex(row => row.id === item.id); if (existing >= 0) rows.value.splice(existing, 1, item); else rows.value.unshift(item); rows.value = rows.value.slice(0, 500) } }
async function clearAll() { if (!window.confirm("Delete all MCP call logs?")) return; await managementApi.clearCalls(); rows.value = [] }
async function remove(item: InvocationRecord) { await managementApi.deleteCall(item.id); rows.value = rows.value.filter(row => row.id !== item.id) }
onMounted(async () => { await load(); connect() })
onBeforeUnmount(() => source?.close())
</script>
<template>
  <div class="space-y-6">
    <PageHeader title="MCP Calls" description="Realtime invocation audit stream and payload inspection.">
      <span class="inline-flex items-center gap-1.5 text-xs" :class="streamLive ? 'text-emerald-500' : 'text-muted-foreground'"><Radio class="size-3.5" />{{ streamLive ? 'live' : 'reconnecting' }}</span>
      <Button variant="outline" size="sm" @click="load"><RefreshCw class="mr-2 size-4" />Refresh</Button>
      <Button variant="destructive" size="sm" @click="clearAll"><Trash2 class="mr-2 size-4" />Clear all</Button>
    </PageHeader>
    <div class="flex gap-3 text-xs text-muted-foreground"><span>{{ rows.length }} loaded</span><span>{{ errorCount }} errors</span></div>
    <p v-if="error" class="text-sm text-destructive">{{ error }}</p>
    <DataTable :columns="columns" :data-source="rows" :loading="loading">
      <template #bodyCell="{ column, record }">
        <template v-if="column.key === 'occurred_at'">{{ formatDate(record.occurred_at) }}</template>
        <template v-else-if="column.key === 'status'"><Tag :color="record.status === 'success' ? 'green' : 'red'">{{ record.status }}</Tag></template>
        <template v-else-if="column.key === 'duration_ms'">{{ Number(record.duration_ms).toFixed(1) }} ms</template>
        <template v-else-if="column.key === 'actions'"><div class="flex gap-1"><Button variant="ghost" size="sm" @click="selected = record">Inspect</Button><Button variant="ghost" size="sm" @click="remove(record)">Delete</Button></div></template>
      </template>
    </DataTable>
    <Modal :open="Boolean(selected)" title="MCP Call" :footer="null" width="860px" @cancel="selected = null">
      <div v-if="selected" class="space-y-4 text-sm">
        <div class="grid gap-3 sm:grid-cols-2"><div><span class="text-muted-foreground">Tool</span><div class="font-medium">{{ selected.tool }}</div></div><div><span class="text-muted-foreground">Request ID</span><div class="break-all font-mono text-xs">{{ selected.request_id || '—' }}</div></div></div>
        <div v-for="[label, value] in [['Arguments', selected.arguments_json], ['Result', selected.result_json], ['Error', selected.error_message]]" :key="label"><div class="mb-1 text-xs font-medium uppercase text-muted-foreground">{{ label }}</div><pre class="max-h-64 overflow-auto rounded-lg bg-muted p-3 text-xs whitespace-pre-wrap">{{ value || '—' }}</pre></div>
      </div>
    </Modal>
  </div>
</template>
