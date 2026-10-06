<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from "vue"
import { InputNumber, Select, Switch } from "ant-design-vue"
import { Save, Trash2 } from "lucide-vue-next"
import { useI18n } from "vue-i18n"

import { managementApi, type BrowserExternalStatus, type BrowserState, type SettingsState } from "@/shared/api/management"
import { ManagementApiError } from "@/shared/api/error"
import { runtimeConfig } from "@/shared/config/runtime"
import { eventBus } from "@/shared/events/bus"
import { setLocale } from "@/shared/i18n"
import { uiPreferences } from "@/shared/lib/preferences"
import { notifications } from "@/shared/notifications/bus"
import { IncompleteSettingsSnapshotError, settingsUpdatePayload } from "@/shared/settings/payload"
import { settingsStore } from "@/shared/settings/store"
import { frontendTelemetry } from "@/shared/telemetry/client"
import Button from "@/shared/ui/Button.vue"
import PageHeader from "@/shared/ui/PageHeader.vue"
import RefreshAction from "@/shared/ui/RefreshAction.vue"
import SectionTabs from "@/shared/ui/SectionTabs.vue"

const { t } = useI18n()
const section = ref("interface")
const state = ref<SettingsState | null>(null)
const browserState = ref<BrowserState | null>(null)
const browserExternalStatus = ref<BrowserExternalStatus | null>(null)
const browserExternalAction = ref<"" | "connect" | "disconnect" | "reset">("")
const browserTheme = ref<"system" | "light" | "dark">("dark")
const loading = ref(false)
const saving = ref(false)
const error = ref("")
const liveTransport = computed(() => eventBus.state.enabled && eventBus.state.status === "connected")
const pageSynced = computed(() => settingsStore.state.synced
  && Boolean(state.value)
  && state.value?.revision === settingsStore.state.value?.revision)
const form = reactive({
  logging_enabled: true,
  logging_capture_payloads: true,
  logging_retention_days: 30,
  logging_max_records: 10000,
  maintenance_interval_minutes: 60,
  terminal_max_exec_timeout_seconds: 21600,
  terminal_max_job_runtime_seconds: 43200,
  mcp_call_timeout_seconds: 5,
  browser_external_enabled: false,
  browser_external_mcp_url: "",
  browser_call_timeout_seconds: 300,
  browser_auto_disconnect_enabled: false,
  browser_idle_timeout_seconds: 300,
  browser_profile_dir_name: "Default",
  browser_extension_token: "",
  browser_clear_extension_token: false,
  reverse_idle_timeout_seconds: 900,
})

const sections = computed(() => [
  { id: "interface", label: t("settings.interface"), description: t("settings.interfaceHint") },
  { id: "browser", label: t("settings.browser"), description: t("settings.browserHint") },
  { id: "realtime", label: t("settings.realtime"), description: t("settings.realtimeHint") },
  { id: "logging", label: t("settings.logging"), description: t("settings.loggingHint") },
  { id: "mcp", label: t("settings.mcp"), description: t("settings.mcpHint") },
])
const languageOptions = [
  { label: "Русский", value: "ru" },
  { label: "English", value: "en" },
]
const themeOptions = computed(() => [
  { label: t("common.system"), value: "system" },
  { label: t("common.dark"), value: "dark" },
  { label: t("common.light"), value: "light" },
])
const densityOptions = computed(() => [
  { label: t("common.comfortable"), value: "comfortable" },
  { label: t("common.compact"), value: "compact" },
])

function readHash(): void {
  const [, child] = location.hash.slice(1).split("/")
  if (["interface", "browser", "realtime", "logging", "mcp"].includes(child ?? "")) section.value = child!
}
function setSection(value: string): void {
  section.value = value
  history.replaceState(null, "", `#settings/${value}`)
}

function formFromState(value: SettingsState) {
  return {
    ...value.management,
    terminal_max_exec_timeout_seconds: value.terminal.max_exec_timeout_seconds,
    terminal_max_job_runtime_seconds: value.terminal.max_job_runtime_seconds,
    mcp_call_timeout_seconds: value.mcp.call_timeout_seconds,
    browser_external_enabled: value.browser.external_enabled,
    browser_external_mcp_url: value.browser.external_mcp_url,
    browser_call_timeout_seconds: value.browser.call_timeout_seconds,
    browser_auto_disconnect_enabled: value.browser.auto_disconnect_enabled,
    browser_idle_timeout_seconds: value.browser.idle_timeout_seconds,
    browser_profile_dir_name: value.browser.profile_dir_name,
    browser_extension_token: "",
    browser_clear_extension_token: false,
    reverse_idle_timeout_seconds: Number(value.analysis.idle_timeout_seconds ?? 900),
  }
}

const dirty = computed(() => state.value
  ? JSON.stringify({ ...form }) !== JSON.stringify(formFromState(state.value))
  : false)

function applyState(value: SettingsState): void {
  state.value = value
  Object.assign(form, formFromState(value))
}

async function load(): Promise<void> {
  loading.value = true
  error.value = ""
  try {
    const fresh = await settingsStore.refresh()
    if (!state.value || !dirty.value) applyState(fresh)
    else if (fresh.revision !== state.value.revision) error.value = String(t("settings.conflict"))
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : "Unable to load settings"
  } finally {
    loading.value = false
  }
}

async function loadBrowser(): Promise<void> {
  try {
    const [managed, external] = await Promise.all([
      managementApi.browserState(),
      managementApi.browserExternalStatus().catch(() => null),
    ])
    browserState.value = managed
    browserExternalStatus.value = external
    const scheme = browserState.value.color_scheme
    if (scheme === "system" || scheme === "light" || scheme === "dark") browserTheme.value = scheme
  } catch (caught) {
    frontendTelemetry.error("settings.browser_load_failed", caught)
  }
}

async function changeBrowserTheme(value: string): Promise<void> {
  if (value !== "system" && value !== "light" && value !== "dark") return
  try {
    browserState.value = await managementApi.setBrowserTheme(value)
    browserTheme.value = browserState.value.color_scheme ?? value
    notifications.success(String(t("notifications.saved")))
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : "Unable to update browser theme"
  }
}

async function save(): Promise<boolean> {
  if (!state.value || loading.value || saving.value) return false
  saving.value = true
  error.value = ""
  try {
    const saved = await managementApi.updateSettings(settingsUpdatePayload(state.value, { ...form }))
    settingsStore.accept(saved)
    applyState(saved)
    error.value = ""
    notifications.success(String(t("notifications.saved")))
    return true
  } catch (caught) {
    error.value = caught instanceof IncompleteSettingsSnapshotError
      ? String(t("settings.reloadBeforeSave"))
      : caught instanceof ManagementApiError && caught.status === 409 && caught.code === "settings_conflict"
        ? String(t("settings.conflict"))
        : caught instanceof Error ? caught.message : "Unable to save settings"
    return false
  } finally {
    saving.value = false
  }
}

async function runExternalBrowserAction(action: "connect" | "disconnect" | "reset"): Promise<void> {
  if (browserExternalAction.value) return
  if (action !== "disconnect" && dirty.value) {
    const saved = await save()
    if (!saved) return
  }
  browserExternalAction.value = action
  error.value = ""
  try {
    browserExternalStatus.value = action === "connect"
      ? await managementApi.browserExternalConnect()
      : action === "disconnect"
        ? await managementApi.browserExternalDisconnect()
        : await managementApi.browserExternalReset()
    notifications.success(String(t("notifications.saved")))
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : "Unable to control external browser"
  } finally {
    browserExternalAction.value = ""
  }
}

async function cleanup(): Promise<void> {
  const result = await managementApi.cleanupLogs()
  notifications.success(String(t("notifications.deleted")), `${result.removed}`)
}

function changeLocale(value: string): void {
  if (value === "en" || value === "ru") setLocale(value)
}

watch(() => settingsStore.state.value, (value) => {
  if (!value) return
  if (!state.value || !dirty.value) {
    applyState(value)
    error.value = ""
  } else if (value.revision !== state.value.revision) {
    error.value = String(t("settings.conflict"))
  }
})

onMounted(() => {
  readHash()
  window.addEventListener("hashchange", readHash)
  if (settingsStore.state.value) applyState(settingsStore.state.value)
  else void settingsStore.ensure().then(applyState).catch((caught) => {
    error.value = caught instanceof Error ? caught.message : "Unable to load settings"
  })
  void loadBrowser()
})
onBeforeUnmount(() => window.removeEventListener("hashchange", readHash))
</script>

<template>
  <div class="space-y-5">
    <PageHeader :title="t('settings.title')" :description="t('settings.description')">
      <RefreshAction :synced="pageSynced" :loading="loading || settingsStore.state.loading" @refresh="load" />
      <Button size="sm" :disabled="saving || loading || !state" @click="save">
        <Save class="mr-2 size-4" />{{ t("common.save") }}
      </Button>
    </PageHeader>

    <SectionTabs :model-value="section" :items="sections" @update:model-value="setSection" />
    <p v-if="error" class="rounded-lg bg-destructive/10 px-4 py-3 text-sm text-destructive">{{ error }}</p>

    <section v-if="section === 'interface'" class="settings-card max-w-3xl">
      <h2>{{ t("settings.interface") }}</h2>
      <label class="setting-row">
        <span><b>{{ t("settings.language") }}</b><small>{{ t("settings.languageHint") }}</small></span>
        <Select :value="uiPreferences.locale.value" :options="languageOptions" class="w-44" @change="changeLocale(String($event))" />
      </label>
      <label class="setting-row">
        <span><b>{{ t("settings.theme") }}</b><small>{{ t("settings.themeHint") }}</small></span>
        <Select v-model:value="uiPreferences.theme.value" :options="themeOptions" class="w-44" />
      </label>
      <label class="setting-row">
        <span><b>{{ t("settings.density") }}</b><small>{{ t("settings.densityHint") }}</small></span>
        <Select v-model:value="uiPreferences.density.value" :options="densityOptions" class="w-44" />
      </label>
    </section>

    <section v-else-if="section === 'browser'" class="settings-card max-w-3xl">
      <h2>{{ t("settings.browser") }}</h2>
      <label class="setting-row">
        <span><b>{{ t("settings.browserTheme") }}</b><small>{{ t("settings.browserThemeHint") }}</small></span>
        <Select :value="browserTheme" :options="themeOptions" class="w-44" @change="changeBrowserTheme(String($event))" />
      </label>
      <div class="setting-row">
        <span><b>{{ t("settings.browserViewport") }}</b><small>{{ t("settings.browserViewportHint") }}</small></span>
        <span class="font-mono text-xs">{{ browserState?.viewport?.width ?? 1280 }} × {{ browserState?.viewport?.height ?? 720 }}</span>
      </div>

      <div class="mt-5 border-t border-border/70 pt-4">
        <h3 class="text-sm font-semibold">{{ t("settings.externalBrowser") }}</h3>
        <p class="mt-1 text-xs text-muted-foreground">{{ t("settings.externalBrowserHint") }}</p>
      </div>
      <label class="setting-row">
        <span><b>{{ t("settings.externalBrowserEnabled") }}</b><small>{{ t("settings.externalBrowserEnabledHint") }}</small></span>
        <Switch v-model:checked="form.browser_external_enabled" />
      </label>
      <label class="setting-row items-start">
        <span><b>{{ t("settings.externalBrowserUrl") }}</b><small>{{ t("settings.externalBrowserUrlHint") }}</small></span>
        <input v-model="form.browser_external_mcp_url" class="field w-full max-w-sm font-mono text-xs" placeholder="http://192.168.1.11:8931/mcp" />
      </label>
      <label class="setting-row">
        <span><b>{{ t("settings.externalBrowserCallTimeout") }}</b><small>{{ t("settings.externalBrowserCallTimeoutHint") }}</small></span>
        <InputNumber v-model:value="form.browser_call_timeout_seconds" :min="1" :max="1800" />
      </label>
      <label class="setting-row">
        <span><b>{{ t("settings.externalBrowserAutoDisconnect") }}</b><small>{{ t("settings.externalBrowserAutoDisconnectHint") }}</small></span>
        <Switch v-model:checked="form.browser_auto_disconnect_enabled" />
      </label>
      <label v-if="form.browser_auto_disconnect_enabled" class="setting-row">
        <span><b>{{ t("settings.externalBrowserIdleTimeout") }}</b><small>{{ t("settings.externalBrowserIdleTimeoutHint") }}</small></span>
        <InputNumber v-model:value="form.browser_idle_timeout_seconds" :min="30" :max="86400" />
      </label>
      <label class="setting-row items-start">
        <span><b>{{ t("settings.externalBrowserProfile") }}</b><small>{{ t("settings.externalBrowserProfileHint") }}</small></span>
        <input v-model="form.browser_profile_dir_name" class="field w-56 font-mono text-xs" placeholder="Default" />
      </label>
      <label class="setting-row items-start">
        <span><b>{{ t("settings.externalBrowserToken") }}</b><small>{{ state?.browser.extension_token_configured ? t("settings.externalBrowserTokenConfigured") : t("settings.externalBrowserTokenHint") }}</small></span>
        <input v-model="form.browser_extension_token" class="field w-full max-w-sm font-mono text-xs" type="password" autocomplete="off" :placeholder="state?.browser.extension_token_configured ? '••••••••' : ''" />
      </label>
      <label v-if="state?.browser.extension_token_configured" class="setting-row">
        <span><b>{{ t("settings.externalBrowserClearToken") }}</b><small>{{ t("settings.externalBrowserClearTokenHint") }}</small></span>
        <Switch v-model:checked="form.browser_clear_extension_token" />
      </label>
      <div class="setting-row">
        <span><b>{{ t("settings.externalBrowserStatus") }}</b><small>{{ browserExternalStatus?.endpoint_origin || form.browser_external_mcp_url || '—' }}</small></span>
        <span class="rounded-md bg-muted px-2 py-1 text-xs" :class="browserExternalStatus?.connected ? 'text-emerald-600' : 'text-muted-foreground'">
          {{ browserExternalStatus?.connected ? t("common.connected") : t("common.disconnected") }}
        </span>
      </div>
      <div class="flex flex-wrap gap-2 pt-3">
        <Button size="sm" :disabled="Boolean(browserExternalAction) || !form.browser_external_enabled || !form.browser_external_mcp_url.trim()" @click="runExternalBrowserAction('connect')">{{ t("settings.externalBrowserConnect") }}</Button>
        <Button variant="outline" size="sm" :disabled="Boolean(browserExternalAction)" @click="runExternalBrowserAction('disconnect')">{{ t("settings.externalBrowserDisconnect") }}</Button>
        <Button variant="outline" size="sm" :disabled="Boolean(browserExternalAction) || !form.browser_external_enabled || !form.browser_external_mcp_url.trim()" @click="runExternalBrowserAction('reset')">{{ t("settings.externalBrowserReset") }}</Button>
      </div>
    </section>

    <section v-else-if="section === 'realtime'" class="settings-card max-w-3xl">
      <h2>{{ t("settings.realtime") }}</h2>
      <label class="setting-row">
        <span><b>{{ t("settings.eventBus") }}</b><small>{{ t("settings.eventBusHint") }}</small></span>
        <span class="rounded-md bg-muted px-2 py-1 text-xs text-muted-foreground">
          {{ liveTransport ? t("common.connected") : t("common.disconnected") }}
        </span>
      </label>
      <label class="setting-row">
        <span><b>{{ t("settings.telemetry") }}</b><small>{{ t("settings.telemetryHint") }}</small></span>
        <Switch v-model:checked="uiPreferences.telemetryEnabled.value" />
      </label>
      <div class="setting-row">
        <span><b>{{ t("settings.telemetryDelivery") }}</b><small>{{ t("settings.telemetryDeliveryHint") }}</small></span>
        <span class="text-right text-xs">
          <b>{{ frontendTelemetry.delivery.status }}</b><br />
          <span class="text-muted-foreground">{{ runtimeConfig.telemetry.endpoint }}</span>
        </span>
      </div>
    </section>

    <section v-else-if="section === 'logging'" class="settings-card max-w-3xl">
      <h2>{{ t("settings.logging") }}</h2>
      <label class="setting-row">
        <span><b>{{ t("settings.loggingEnabled") }}</b><small>{{ t("settings.loggingEnabledHint") }}</small></span>
        <Switch v-model:checked="form.logging_enabled" />
      </label>
      <label class="setting-row">
        <span><b>{{ t("settings.capturePayloads") }}</b><small>{{ t("settings.capturePayloadsHint") }}</small></span>
        <Switch v-model:checked="form.logging_capture_payloads" />
      </label>
      <label class="setting-row"><span><b>{{ t("settings.retentionDays") }}</b></span><InputNumber v-model:value="form.logging_retention_days" :min="1" :max="3650" /></label>
      <label class="setting-row"><span><b>{{ t("settings.maxRecords") }}</b></span><InputNumber v-model:value="form.logging_max_records" :min="100" :max="1000000" /></label>
      <label class="setting-row"><span><b>{{ t("settings.cleanupInterval") }}</b></span><InputNumber v-model:value="form.maintenance_interval_minutes" :min="1" :max="1440" /></label>
      <Button variant="outline" size="sm" @click="cleanup"><Trash2 class="mr-2 size-4" />{{ t("settings.applyRetention") }}</Button>
    </section>

    <section v-else class="settings-card max-w-3xl">
      <h2>{{ t("settings.mcp") }}</h2>
      <label class="setting-row">
        <span><b>{{ t("settings.callTimeout") }}</b><small>{{ t("settings.callTimeoutHint") }}</small></span>
        <InputNumber v-model:value="form.mcp_call_timeout_seconds" :min="1" :max="300" />
      </label>
    </section>

    <section class="max-w-3xl rounded-xl border border-border/70 bg-card p-4">
      <h2 class="text-sm font-semibold">{{ t("settings.domain") }}</h2>
      <p class="mt-1 text-xs text-muted-foreground">{{ t("settings.domainHint") }}</p>
    </section>
  </div>
</template>
