<script setup lang="ts">
import { onMounted, reactive, ref } from "vue"
import { InputNumber, Switch } from "ant-design-vue"
import { RefreshCw, Save, Trash2 } from "lucide-vue-next"
import { managementApi, type SettingsState } from "@/shared/api/management"
import Button from "@/shared/ui/Button.vue"
import PageHeader from "@/shared/ui/PageHeader.vue"

const state = ref<SettingsState | null>(null); const loading = ref(false); const saving = ref(false); const error = ref(""); const message = ref("")
const form = reactive({ logging_enabled: true, logging_capture_payloads: true, logging_retention_days: 30, logging_max_records: 10000, maintenance_interval_minutes: 60, terminal_max_exec_timeout_seconds: 21600, terminal_max_job_runtime_seconds: 43200, mcp_call_timeout_seconds: 5, reverse_idle_timeout_seconds: 900 })
async function load() { loading.value = true; error.value = ""; try { state.value = await managementApi.settings(); Object.assign(form, { ...state.value.management, terminal_max_exec_timeout_seconds: state.value.terminal.max_exec_timeout_seconds, terminal_max_job_runtime_seconds: state.value.terminal.max_job_runtime_seconds, mcp_call_timeout_seconds: state.value.mcp.call_timeout_seconds, reverse_idle_timeout_seconds: Number(state.value.analysis.idle_timeout_seconds ?? 900) }) } catch (e) { error.value = e instanceof Error ? e.message : "Unable to load settings" } finally { loading.value = false } }
async function save() { saving.value = true; message.value = ""; error.value = ""; try { state.value = await managementApi.updateSettings({ ...form }); message.value = "Settings saved" } catch (e) { error.value = e instanceof Error ? e.message : "Unable to save settings" } finally { saving.value = false } }
async function cleanup() { const result = await managementApi.cleanupLogs(); message.value = `Removed ${result.removed} expired call records` }
onMounted(load)
</script>
<template>
  <div class="space-y-6">
    <PageHeader title="Settings" description="Runtime policy and retention controls."><Button variant="outline" size="sm" @click="load"><RefreshCw class="mr-2 size-4" />Reload</Button><Button size="sm" :disabled="saving" @click="save"><Save class="mr-2 size-4" />Save</Button></PageHeader>
    <p v-if="error" class="rounded-lg bg-destructive/10 px-4 py-3 text-sm text-destructive">{{ error }}</p><p v-if="message" class="rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-4 py-3 text-sm text-emerald-600">{{ message }}</p>
    <div class="grid gap-5 lg:grid-cols-2">
      <section class="settings-card"><h2>Invocation logging</h2><label class="setting-row"><span><b>Logging enabled</b><small>Persist MCP invocation audit records.</small></span><Switch v-model:checked="form.logging_enabled" /></label><label class="setting-row"><span><b>Capture payloads</b><small>Store arguments, results and error details.</small></span><Switch v-model:checked="form.logging_capture_payloads" /></label><label class="setting-row"><span><b>Retention days</b></span><InputNumber v-model:value="form.logging_retention_days" :min="1" :max="3650" /></label><label class="setting-row"><span><b>Maximum records</b></span><InputNumber v-model:value="form.logging_max_records" :min="100" :max="1000000" /></label><label class="setting-row"><span><b>Cleanup interval (minutes)</b></span><InputNumber v-model:value="form.maintenance_interval_minutes" :min="1" :max="1440" /></label><Button variant="outline" size="sm" @click="cleanup"><Trash2 class="mr-2 size-4" />Apply retention now</Button></section>
      <section class="settings-card"><h2>Terminal runtime</h2><label class="setting-row"><span><b>Max exec timeout</b><small>Seconds</small></span><InputNumber v-model:value="form.terminal_max_exec_timeout_seconds" :min="1" :max="86400" /></label><label class="setting-row"><span><b>Max job runtime</b><small>Seconds</small></span><InputNumber v-model:value="form.terminal_max_job_runtime_seconds" :min="1" :max="604800" /></label></section>
      <section class="settings-card"><h2>MCP runtime</h2><label class="setting-row"><span><b>Call timeout</b><small>Seconds per proxied backend call.</small></span><InputNumber v-model:value="form.mcp_call_timeout_seconds" :min="1" :max="300" /></label></section>
      <section class="settings-card"><h2>Analysis sessions</h2><label class="setting-row"><span><b>Idle release timeout</b><small>0 disables automatic release.</small></span><InputNumber v-model:value="form.reverse_idle_timeout_seconds" :min="0" :max="86400" /></label><div v-if="state" class="mt-3 text-xs text-muted-foreground">Source: {{ state.analysis.source || 'unknown' }} · auto release {{ state.analysis.auto_release_enabled ? 'enabled' : 'disabled' }}</div></section>
    </div>
  </div>
</template>
