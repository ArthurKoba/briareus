<script setup lang="ts">
import { computed, onMounted, ref } from "vue"
import { Modal, Tag } from "ant-design-vue"
import { RefreshCw, Trash2 } from "lucide-vue-next"
import { managementApi, type TerminalJobState, type TerminalState } from "@/shared/api/management"
import { formatBytes, formatDate, textValue } from "@/shared/lib/format"
import Button from "@/shared/ui/Button.vue"
import DataTable from "@/shared/ui/DataTable.vue"
import PageHeader from "@/shared/ui/PageHeader.vue"
import StatCard from "@/shared/ui/StatCard.vue"

const state = ref<TerminalState | null>(null); const loading = ref(false); const error = ref(""); const selected = ref<TerminalJobState | null>(null)
const jobs = computed(() => state.value?.jobs ?? []); const workspaces = computed(() => state.value?.workspaces ?? [])
const running = computed(() => jobs.value.filter(item => ["running", "cancelling"].includes(String(item.state))).length)
const failed = computed(() => jobs.value.filter(item => ["failed", "interrupted"].includes(String(item.state))).length)
const workspaceColumns = [{ title: "Workspace", dataIndex: "workspace_id", key: "workspace_id" }, { title: "Active jobs", dataIndex: "active_jobs", key: "active_jobs", width: 120 }, { title: "Path", dataIndex: "path", key: "path" }, { title: "Actions", key: "actions", width: 100 }]
const jobColumns = [{ title: "Job", dataIndex: "job_id", key: "job_id", width: 150 }, { title: "Workspace", dataIndex: "workspace_id", key: "workspace_id", width: 150 }, { title: "State", dataIndex: "state", key: "state", width: 110 }, { title: "Duration", dataIndex: "duration_seconds", key: "duration_seconds", width: 100 }, { title: "Command", dataIndex: "command", key: "command" }, { title: "Actions", key: "actions", width: 190 }]
async function load() { loading.value = true; error.value = ""; try { state.value = await managementApi.terminal() } catch (e) { error.value = e instanceof Error ? e.message : "Unable to load terminal" } finally { loading.value = false } }
async function inspect(id: string) { selected.value = await managementApi.terminalJob(id) }
async function cancel(id: string) { await managementApi.cancelTerminalJob(id); await load(); if (selected.value) await inspect(id) }
async function deleteJob(id: string) { if (!window.confirm(`Delete retained job ${id}?`)) return; await managementApi.deleteTerminalJob(id); await load() }
async function deleteWorkspace(id: string) { if (!window.confirm(`Delete workspace ${id}?`)) return; await managementApi.deleteWorkspace(id); await load() }
async function cleanup() { if (!window.confirm("Delete terminal jobs older than 7 days?")) return; await managementApi.cleanupTerminalJobs(168); await load() }
onMounted(load)
</script>
<template>
  <div class="space-y-6">
    <PageHeader title="Terminal" description="Persistent workspaces and retained job lifecycle."><Button variant="outline" size="sm" @click="load"><RefreshCw class="mr-2 size-4" />Refresh</Button><Button variant="outline" size="sm" @click="cleanup"><Trash2 class="mr-2 size-4" />Cleanup 7d+</Button></PageHeader>
    <p v-if="error" class="text-sm text-destructive">{{ error }}</p>
    <div v-if="state" class="grid gap-4 sm:grid-cols-2 xl:grid-cols-4"><StatCard label="Workspaces" :value="workspaces.length" /><StatCard label="Jobs" :value="jobs.length" /><StatCard label="Running" :value="running" /><StatCard label="Failed" :value="failed" /></div>
    <section v-if="state" class="rounded-xl border border-border bg-card p-4 text-sm"><div class="grid gap-3 sm:grid-cols-2 lg:grid-cols-4"><div><span class="text-muted-foreground">Shell</span><div class="font-mono text-xs">{{ textValue(state.status.shell) }}</div></div><div><span class="text-muted-foreground">Workspace root</span><div class="font-mono text-xs">{{ textValue(state.status.workspace_root) }}</div></div><div><span class="text-muted-foreground">Free disk</span><div>{{ formatBytes(state.status?.disk && typeof state.status.disk === 'object' ? state.status.disk.free_bytes : undefined) }}</div></div><div><span class="text-muted-foreground">Git configured</span><div>{{ state.status.git_configured ? 'yes' : 'no' }}</div></div></div></section>
    <div class="space-y-3"><h2 class="text-sm font-semibold">Workspaces</h2><DataTable :columns="workspaceColumns" :data-source="workspaces" :loading="loading" row-key="workspace_id"><template #bodyCell="{ column, record }"><template v-if="column.key === 'actions'"><Button variant="ghost" size="sm" @click="deleteWorkspace(record.workspace_id)">Delete</Button></template></template></DataTable></div>
    <div class="space-y-3"><h2 class="text-sm font-semibold">Jobs</h2><DataTable :columns="jobColumns" :data-source="jobs" :loading="loading" row-key="job_id"><template #bodyCell="{ column, record }"><template v-if="column.key === 'state'"><Tag :color="record.state === 'running' ? 'green' : record.state === 'failed' ? 'red' : 'default'">{{ record.state }}</Tag></template><template v-else-if="column.key === 'job_id'"><button class="font-mono text-xs underline" @click="inspect(record.job_id)">{{ String(record.job_id).slice(0, 12) }}</button></template><template v-else-if="column.key === 'actions'"><div class="flex gap-1"><Button variant="ghost" size="sm" @click="inspect(record.job_id)">Inspect</Button><Button v-if="['running','cancelling'].includes(record.state)" variant="ghost" size="sm" @click="cancel(record.job_id)">Cancel</Button><Button v-else variant="ghost" size="sm" @click="deleteJob(record.job_id)">Delete</Button></div></template></template></DataTable></div>
    <Modal :open="Boolean(selected)" title="Terminal job" :footer="null" width="900px" @cancel="selected = null"><div v-if="selected" class="space-y-4 text-sm"><div class="grid gap-3 sm:grid-cols-3"><div><span class="text-muted-foreground">State</span><div>{{ textValue(selected.job.state) }}</div></div><div><span class="text-muted-foreground">Workspace</span><div>{{ textValue(selected.job.workspace_id) }}</div></div><div><span class="text-muted-foreground">Started</span><div>{{ formatDate(selected.job.started_at) }}</div></div></div><pre class="max-h-[55vh] overflow-auto rounded-lg bg-black p-4 text-xs text-zinc-200 whitespace-pre-wrap">{{ textValue(selected.tail.output) }}</pre></div></Modal>
  </div>
</template>
