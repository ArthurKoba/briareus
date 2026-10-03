<script setup lang="ts">
import { onMounted, reactive, ref } from "vue"
import { InputNumber, Select, Switch } from "ant-design-vue"
import { RefreshCw, Save, Trash2 } from "lucide-vue-next"
import { useI18n } from "vue-i18n"
import { managementApi, type SettingsState } from "@/shared/api/management"
import { uiPreferences } from "@/shared/lib/preferences"
import { setLocale } from "@/shared/i18n"
import { runtimeConfig } from "@/shared/config/runtime"
import { eventBus } from "@/shared/events/bus"
import { notifications } from "@/shared/notifications/bus"
import Button from "@/shared/ui/Button.vue"
import PageHeader from "@/shared/ui/PageHeader.vue"

const {t}=useI18n()
const state=ref<SettingsState|null>(null),loading=ref(false),saving=ref(false),error=ref("")
const form=reactive({logging_enabled:true,logging_capture_payloads:true,logging_retention_days:30,logging_max_records:10000,maintenance_interval_minutes:60,terminal_max_exec_timeout_seconds:21600,terminal_max_job_runtime_seconds:43200,mcp_call_timeout_seconds:5,reverse_idle_timeout_seconds:900})
const languageOptions=[{label:"Русский",value:"ru"},{label:"English",value:"en"}],themeOptions=[{label:"System",value:"system"},{label:"Dark",value:"dark"},{label:"Light",value:"light"}],densityOptions=[{label:"Comfortable",value:"comfortable"},{label:"Compact",value:"compact"}]
async function load(){loading.value=true;error.value="";try{state.value=await managementApi.settings();Object.assign(form,{...state.value.management,terminal_max_exec_timeout_seconds:state.value.terminal.max_exec_timeout_seconds,terminal_max_job_runtime_seconds:state.value.terminal.max_job_runtime_seconds,mcp_call_timeout_seconds:state.value.mcp.call_timeout_seconds,reverse_idle_timeout_seconds:Number(state.value.analysis.idle_timeout_seconds??900)})}catch(e){error.value=e instanceof Error?e.message:"Unable to load settings"}finally{loading.value=false}}
async function save(){saving.value=true;error.value="";try{state.value=await managementApi.updateSettings({...form});notifications.success(String(t("notifications.saved")))}catch(e){error.value=e instanceof Error?e.message:"Unable to save settings"}finally{saving.value=false}}
async function cleanup(){const result=await managementApi.cleanupLogs();notifications.success(String(t("notifications.deleted")),`${result.removed} expired call records`)}
function changeLocale(value:string){if(value==="en"||value==="ru")setLocale(value)}
onMounted(load)
</script>
<template><div class="space-y-6"><PageHeader :title="t('settings.title')" :description="t('settings.description')"><Button variant="outline" size="sm" @click="load"><RefreshCw class="mr-2 size-4"/>{{t('common.refresh')}}</Button><Button size="sm" :disabled="saving" @click="save"><Save class="mr-2 size-4"/>{{t('common.save')}}</Button></PageHeader><p v-if="error" class="rounded-lg bg-destructive/10 px-4 py-3 text-sm text-destructive">{{error}}</p>
<div class="grid gap-5 lg:grid-cols-2">
<section class="settings-card"><h2>{{t('settings.interface')}}</h2><label class="setting-row"><span><b>{{t('settings.language')}}</b><small>UI translations are browser-local.</small></span><Select :value="uiPreferences.locale.value" :options="languageOptions" class="w-40" @change="changeLocale(String($event))"/></label><label class="setting-row"><span><b>{{t('settings.theme')}}</b><small>System follows the browser/OS preference.</small></span><Select v-model:value="uiPreferences.theme.value" :options="themeOptions" class="w-40"/></label><label class="setting-row"><span><b>{{t('settings.density')}}</b><small>Affects dense management tables.</small></span><Select v-model:value="uiPreferences.density.value" :options="densityOptions" class="w-40"/></label></section>
<section class="settings-card"><h2>{{t('settings.realtime')}}</h2><div class="setting-row"><span><b>{{t('settings.eventBus')}}</b><small>{{t('settings.eventBusHint')}}</small></span><span class="rounded-md bg-muted px-2 py-1 font-mono text-xs">{{eventBus.state.status}} · {{eventBus.state.subscriptions}}</span></div><div class="setting-row"><span><b>{{t('settings.telemetry')}}</b><small>{{t('settings.telemetryHint')}}</small></span><span class="text-right text-xs"><b>{{runtimeConfig.telemetry.enabled?t('common.enabled'):t('common.disabled')}}</b><br><span class="text-muted-foreground">{{runtimeConfig.telemetry.endpoint}}</span></span></div></section>
<section class="settings-card"><h2>{{t('settings.logging')}}</h2><label class="setting-row"><span><b>Logging enabled</b><small>Persist MCP invocation audit records.</small></span><Switch v-model:checked="form.logging_enabled"/></label><label class="setting-row"><span><b>Capture payloads</b><small>Store arguments, results and error details.</small></span><Switch v-model:checked="form.logging_capture_payloads"/></label><label class="setting-row"><span><b>Retention days</b></span><InputNumber v-model:value="form.logging_retention_days" :min="1" :max="3650"/></label><label class="setting-row"><span><b>Maximum records</b></span><InputNumber v-model:value="form.logging_max_records" :min="100" :max="1000000"/></label><label class="setting-row"><span><b>Cleanup interval (minutes)</b></span><InputNumber v-model:value="form.maintenance_interval_minutes" :min="1" :max="1440"/></label><Button variant="outline" size="sm" @click="cleanup"><Trash2 class="mr-2 size-4"/>Apply retention now</Button></section>
<section class="settings-card"><h2>{{t('settings.mcp')}}</h2><label class="setting-row"><span><b>Call timeout</b><small>Seconds per proxied backend call.</small></span><InputNumber v-model:value="form.mcp_call_timeout_seconds" :min="1" :max="300"/></label></section>
</div><section class="rounded-xl border border-border bg-card p-5"><h2 class="text-sm font-semibold">{{t('settings.domain')}}</h2><p class="mt-1 text-xs text-muted-foreground">{{t('settings.domainHint')}}</p></section></div></template>
