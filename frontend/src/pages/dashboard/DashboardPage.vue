<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from "vue"
import { RefreshCw } from "lucide-vue-next"
import { useI18n } from "vue-i18n"
import { managementApi, type DashboardState } from "@/shared/api/management"
import { eventBus, type BusEvent } from "@/shared/events/bus"
import { formatBytes } from "@/shared/lib/format"
import Button from "@/shared/ui/Button.vue"
import PageHeader from "@/shared/ui/PageHeader.vue"
import StatCard from "@/shared/ui/StatCard.vue"

const {t}=useI18n()
const data=ref<DashboardState|null>(null),loading=ref(false),error=ref("")
let unsubscribe:undefined|(()=>void)
function accept(event:BusEvent){if(event.type==="snapshot"||event.type==="metrics")data.value=event.data as DashboardState}
async function load(){loading.value=true;error.value="";try{const snapshot=await managementApi.dashboard();data.value=snapshot;eventBus.publishMock("dashboard.metrics","snapshot",snapshot)}catch(e){error.value=e instanceof Error?e.message:"Unable to load dashboard"}finally{loading.value=false}}
onMounted(async()=>{unsubscribe=eventBus.subscribe("dashboard.metrics",accept);await load()})
onBeforeUnmount(()=>unsubscribe?.())
</script>
<template><div class="space-y-6"><PageHeader :title="t('nav.dashboard')" description="Live management state across the MCP control plane."><span class="rounded-md bg-muted px-2 py-1 text-[10px] uppercase text-muted-foreground">{{eventBus.state.status}}</span><Button variant="outline" size="sm" :disabled="loading" @click="load"><RefreshCw class="mr-2 size-4"/>{{t('common.refresh')}}</Button></PageHeader><p v-if="error" class="rounded-lg border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-destructive">{{error}}</p><div v-if="data" class="grid gap-4 sm:grid-cols-2 xl:grid-cols-4"><StatCard label="Active accounts" :value="data.accounts.enabled" :hint="`${data.accounts.total} configured`"/><StatCard label="MCP calls" :value="data.calls.total" :hint="`${data.calls.error_rate}% error rate`"/><StatCard label="Average latency" :value="`${data.calls.average_duration_ms} ms`" :hint="`${data.calls.errors} errors`"/><StatCard label="OAuth sessions" :value="data.oauth.active" :hint="`${data.oauth.tracked} tracked`"/><StatCard label="Analysis projects" :value="data.analysis.projects" :hint="`${data.analysis.active_sessions} active sessions`"/><StatCard label="Workers" :value="data.analysis.workers" :hint="`${data.analysis.running_workers} running`"/><StatCard label="Workspace free" :value="formatBytes(data.workspace.free_bytes)" :hint="`${String(data.workspace.files??0)} files`"/><StatCard label="Workspace size" :value="formatBytes(data.workspace.size_bytes)" hint="cached workspace snapshot"/></div><section v-if="data" class="rounded-xl border border-border bg-card p-5 shadow-sm"><h2 class="text-sm font-semibold">Account providers</h2><div class="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4"><div v-for="(value,provider) in data.accounts.by_provider" :key="provider" class="rounded-lg bg-muted px-4 py-3"><div class="text-xs uppercase text-muted-foreground">{{provider}}</div><div class="mt-1 text-xl font-semibold">{{value}}</div></div></div></section></div></template>
