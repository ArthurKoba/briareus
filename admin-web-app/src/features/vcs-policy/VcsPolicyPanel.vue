<script setup lang="ts">
import { computed, reactive, ref, watch } from "vue"
import { Switch } from "ant-design-vue"
import { AlertTriangle, GitCommitHorizontal, RotateCcw, Save, ShieldCheck } from "lucide-vue-next"
import { useI18n } from "vue-i18n"

import { managementApi, type VcsPolicyState } from "@/shared/api/management"
import { ManagementApiError } from "@/shared/api/error"
import { notifications } from "@/shared/notifications/bus"
import { settingsUpdatePayload, type SettingsUpdatePayload } from "@/shared/settings/payload"
import { settingsStore } from "@/shared/settings/store"
import Button from "@/shared/ui/Button.vue"
import RefreshAction from "@/shared/ui/RefreshAction.vue"

type Provider = "github" | "gitlab"
const props = defineProps<{ provider: Provider }>()
const { t } = useI18n()

const saving = ref(false)
const loading = ref(false)
const error = ref("")
const baseline = ref("")
const draft = reactive<VcsPolicyState>({
  local_first_guidance: true,
  local_git_transport_enabled: false,
  remote_source_mutations_enabled: false,
})

const serverPolicy = computed(() => settingsStore.state.value?.[props.provider] ?? null)
const encodedDraft = computed(() => JSON.stringify(draft))
const dirty = computed(() => Boolean(baseline.value) && encodedDraft.value !== baseline.value)
const serverChanged = computed(() => {
  if (!dirty.value || !serverPolicy.value || !baseline.value) return false
  return JSON.stringify(serverPolicy.value) !== baseline.value
})
const providerLabel = computed(() => props.provider === "github" ? "GitHub" : "GitLab")

function applyPolicy(policy: VcsPolicyState): void {
  Object.assign(draft, policy)
  baseline.value = JSON.stringify(policy)
  error.value = ""
}

function policyOverrides(): Partial<SettingsUpdatePayload> {
  if (props.provider === "github") return {
    github_local_first_guidance: draft.local_first_guidance,
    github_local_git_transport_enabled: draft.local_git_transport_enabled,
    github_remote_source_mutations_enabled: draft.remote_source_mutations_enabled,
  }
  return {
    gitlab_local_first_guidance: draft.local_first_guidance,
    gitlab_local_git_transport_enabled: draft.local_git_transport_enabled,
    gitlab_remote_source_mutations_enabled: draft.remote_source_mutations_enabled,
  }
}

async function refresh(): Promise<void> {
  loading.value = true
  error.value = ""
  try {
    const value = await settingsStore.refresh()
    applyPolicy(value[props.provider])
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : String(t("git.policyLoadError"))
  } finally {
    loading.value = false
  }
}

async function save(): Promise<void> {
  const snapshot = settingsStore.state.value
  if (!snapshot || !dirty.value || saving.value || serverChanged.value) return
  saving.value = true
  error.value = ""
  try {
    const saved = await managementApi.updateSettings(
      settingsUpdatePayload(snapshot, policyOverrides()),
    )
    settingsStore.accept(saved)
    applyPolicy(saved[props.provider])
    notifications.success(String(t("notifications.saved")), providerLabel.value)
  } catch (caught) {
    if (caught instanceof ManagementApiError && caught.status === 409) {
      error.value = String(t("git.policyConflict"))
      await settingsStore.refresh().catch(() => undefined)
    } else {
      error.value = caught instanceof Error ? caught.message : String(t("git.policySaveError"))
    }
  } finally {
    saving.value = false
  }
}

watch(serverPolicy, (policy) => {
  if (!policy) return
  if (!baseline.value || !dirty.value) applyPolicy(policy)
}, { immediate: true })

watch(() => props.provider, () => {
  baseline.value = ""
  const policy = serverPolicy.value
  if (policy) applyPolicy(policy)
})
</script>

<template>
  <section class="space-y-4">
    <div class="flex flex-wrap items-start justify-between gap-3">
      <div>
        <h2 class="text-lg font-semibold">{{ providerLabel }} · {{ t("git.parameters") }}</h2>
        <p class="mt-1 max-w-3xl text-sm text-muted-foreground">{{ t("git.policyDescription") }}</p>
      </div>
      <div class="flex items-center gap-2">
        <RefreshAction :synced="settingsStore.state.synced && !serverChanged" :loading="loading || settingsStore.state.loading" @refresh="refresh" />
        <Button v-if="dirty" variant="outline" size="sm" @click="serverPolicy && applyPolicy(serverPolicy)">
          <RotateCcw class="mr-2 size-4" />{{ t("git.resetPolicy") }}
        </Button>
        <Button size="sm" :disabled="!dirty || saving || serverChanged || !settingsStore.state.value" @click="save">
          <Save class="mr-2 size-4" />{{ t("common.save") }}
        </Button>
      </div>
    </div>

    <p v-if="serverChanged" class="rounded-lg border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-sm text-amber-700 dark:text-amber-300">
      {{ t("git.policyConflict") }}
    </p>
    <p v-if="error" class="rounded-lg border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-destructive">{{ error }}</p>

    <div class="overflow-hidden rounded-xl border border-border/70 bg-card">
      <label class="setting-row border-b border-border/60 px-4 py-4">
        <span class="flex min-w-0 gap-3">
          <ShieldCheck class="mt-0.5 size-4 shrink-0 text-muted-foreground" />
          <span>
            <b>{{ t("git.localFirstGuidance") }}</b>
            <small>{{ t("git.localFirstGuidanceHint") }}</small>
          </span>
        </span>
        <Switch v-model:checked="draft.local_first_guidance" />
      </label>
      <label class="setting-row border-b border-border/60 px-4 py-4">
        <span class="flex min-w-0 gap-3">
          <GitCommitHorizontal class="mt-0.5 size-4 shrink-0 text-muted-foreground" />
          <span>
            <b>{{ t("git.localGitTransport") }}</b>
            <small>{{ t("git.localGitTransportHint") }}</small>
          </span>
        </span>
        <Switch v-model:checked="draft.local_git_transport_enabled" />
      </label>
      <label class="setting-row px-4 py-4">
        <span class="flex min-w-0 gap-3">
          <AlertTriangle class="mt-0.5 size-4 shrink-0" :class="draft.remote_source_mutations_enabled ? 'text-amber-500' : 'text-muted-foreground'" />
          <span>
            <b>{{ t("git.remoteSourceMutations") }}</b>
            <small>{{ t("git.remoteSourceMutationsHint") }}</small>
          </span>
        </span>
        <Switch v-model:checked="draft.remote_source_mutations_enabled" />
      </label>
    </div>

    <div class="rounded-xl border border-border/70 bg-muted/20 px-4 py-3 text-xs leading-5 text-muted-foreground">
      <b class="text-foreground">{{ t("git.policyBoundaryTitle") }}</b>
      {{ t("git.policyBoundaryHint") }}
    </div>

    <div v-if="draft.remote_source_mutations_enabled" class="rounded-xl border border-amber-500/25 bg-amber-500/10 px-4 py-3 text-xs leading-5 text-amber-700 dark:text-amber-300">
      {{ t("git.remoteSourceWarning") }}
    </div>
  </section>
</template>
