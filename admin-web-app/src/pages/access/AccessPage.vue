<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from "vue"
import { Select, Switch } from "ant-design-vue"
import { ShieldCheck } from "lucide-vue-next"
import { useI18n } from "vue-i18n"

import {
  adminApi,
  type AccessControlRecord,
  type AccessRequestRecord,
  type AccessSessionRecord,
  type AccountScope,
  type EnforcementMode,
} from "@/shared/api/admin"
import { eventBus } from "@/shared/events/bus"
import { notifications } from "@/shared/notifications/bus"
import Button from "@/shared/ui/Button.vue"
import PageHeader from "@/shared/ui/PageHeader.vue"
import RefreshAction from "@/shared/ui/RefreshAction.vue"

const { t } = useI18n()
const sessions = ref<AccessSessionRecord[]>([])
const requests = ref<AccessRequestRecord[]>([])
const controls = ref<AccessControlRecord[]>([])
const loading = ref(false)
const saving = ref(false)
const error = ref("")
let unsubscribe: undefined | (() => void)

type SessionDraft = {
  access_level: "read_only" | "full_access"
  account_scope: AccountScope
  account_ids: string
  expires_at: number
  label: string
}
const drafts = reactive<Record<string, SessionDraft>>({})

type RequestDraft = {
  account_scope: AccountScope
  account_ids: string
  expires_at: number
}
const requestDrafts = reactive<Record<string, RequestDraft>>({})

const surfaceNames = computed(() => new Map(controls.value.map(item => [item.surface_id, item.surface])))
const sortedControls = computed(() => [...controls.value].sort((a, b) => a.surface_id - b.surface_id))

function syncDrafts(): void {
  for (const session of sessions.value) {
    if (drafts[session.id]) continue
    drafts[session.id] = {
      access_level: session.access_level,
      account_scope: session.account_scope,
      account_ids: session.account_ids.join(", "),
      expires_at: session.expires_at,
      label: session.label,
    }
  }
}

function syncRequestDrafts(): void {
  const live = new Set(requests.value.map(item => item.id))
  for (const key of Object.keys(requestDrafts)) {
    if (!live.has(key)) delete requestDrafts[key]
  }
  for (const request of requests.value) {
    if (requestDrafts[request.id]) continue
    requestDrafts[request.id] = {
      account_scope: request.requested_account_scope,
      account_ids: request.requested_account_ids.join(", "),
      expires_at: request.requested_expires_at,
    }
  }
}

async function load(): Promise<void> {
  loading.value = true
  error.value = ""
  try {
    const [sessionData, requestData, controlData] = await Promise.all([
      adminApi.accessSessions(),
      adminApi.accessRequests(),
      adminApi.accessControls(),
    ])
    sessions.value = sessionData.sessions
    requests.value = requestData.requests
    controls.value = controlData.controls
    syncDrafts()
    syncRequestDrafts()
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : String(caught)
  } finally {
    loading.value = false
  }
}

async function setControl(item: AccessControlRecord, enabled: boolean): Promise<void> {
  const mode: EnforcementMode = enabled ? "session_enforced" : "unrestricted"
  saving.value = true
  try {
    const result = await adminApi.updateAccessControls([{ surface_id: item.surface_id, mode }])
    for (const changed of result.controls) {
      const local = controls.value.find(control => control.surface_id === changed.surface_id)
      if (local) local.mode = changed.mode
    }
  } finally {
    saving.value = false
  }
}

async function setAll(mode: EnforcementMode): Promise<void> {
  saving.value = true
  try {
    const result = await adminApi.updateAccessControls(
      controls.value.map(item => ({ surface_id: item.surface_id, mode })),
    )
    const byId = new Map(result.controls.map(item => [item.surface_id, item.mode]))
    controls.value = controls.value.map(item => ({
      ...item,
      mode: byId.get(item.surface_id) ?? item.mode,
    }))
  } finally {
    saving.value = false
  }
}

function requestedScope(request: AccessRequestRecord): string {
  if (request.requested_account_scope !== "selected") return request.requested_account_scope
  return request.requested_account_scope + ": " + request.requested_account_ids.join(", ")
}

async function resolve(request: AccessRequestRecord, approve: boolean): Promise<void> {
  const draft = requestDrafts[request.id]
  saving.value = true
  try {
    const accountIds = draft?.account_scope === "selected"
      ? draft.account_ids.split(",").map(value => value.trim()).filter(Boolean)
      : []
    await adminApi.resolveAccessRequest(request.id, {
      approve,
      ...(approve && request.kind === "full_access"
        ? {
            account_scope: draft?.account_scope ?? request.requested_account_scope,
            account_ids: accountIds,
          }
        : {}),
      ...(approve && request.kind === "extension"
        ? { expires_at: draft?.expires_at ?? request.requested_expires_at }
        : {}),
    })
    notifications.success(String(t("notifications.saved")))
    await load()
  } finally {
    saving.value = false
  }
}

async function saveSession(session: AccessSessionRecord): Promise<void> {
  const draft = drafts[session.id]
  if (!draft) return
  const ids = draft.account_scope === "selected"
    ? draft.account_ids.split(",").map(value => value.trim()).filter(Boolean)
    : []
  saving.value = true
  try {
    const updated = await adminApi.updateAccessSession(session.id, {
      access_level: draft.access_level,
      account_scope: draft.account_scope,
      account_ids: ids,
      expires_at: Number(draft.expires_at) || 0,
      label: draft.label,
    })
    const index = sessions.value.findIndex(item => item.id === session.id)
    if (index >= 0) sessions.value[index] = updated
    delete drafts[session.id]
    syncDrafts()
    notifications.success(String(t("notifications.saved")))
  } finally {
    saving.value = false
  }
}

async function revoke(session: AccessSessionRecord): Promise<void> {
  saving.value = true
  try {
    await adminApi.revokeAccessSession(session.id)
    await load()
  } finally {
    saving.value = false
  }
}

function expiry(value: number): string {
  if (!value) return String(t("access.never"))
  return new Date(value * 1000).toLocaleString()
}

onMounted(() => {
  unsubscribe = eventBus.subscribe("access.sessions", () => { void load() })
  void load()
})
onBeforeUnmount(() => unsubscribe?.())
</script>

<template>
  <div class="space-y-6">
    <PageHeader :title="t('access.title')" :description="t('access.description')">
      <template #actions>
        <RefreshAction :synced="false" :loading="loading" @refresh="load" />
      </template>
    </PageHeader>

    <p v-if="error" class="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">{{ error }}</p>

    <section class="settings-card">
      <div class="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 class="m-0">{{ t("access.controls") }}</h2>
          <p class="mt-1 text-xs text-muted-foreground">{{ t("access.controlsHint") }}</p>
        </div>
        <div class="flex gap-2">
          <Button size="sm" variant="outline" :disabled="saving" @click="setAll('unrestricted')">{{ t("access.allUnrestricted") }}</Button>
          <Button size="sm" :disabled="saving" @click="setAll('session_enforced')">{{ t("access.allEnforced") }}</Button>
        </div>
      </div>
      <div class="mt-4 grid gap-2 md:grid-cols-2 xl:grid-cols-4">
        <div v-for="item in sortedControls" :key="item.surface_id" class="flex items-center justify-between rounded-lg border border-border px-3 py-3">
          <div>
            <div class="text-sm font-medium">{{ item.surface }}</div>
            <div class="text-xs text-muted-foreground">{{ item.mode }}</div>
          </div>
          <Switch
            :checked="item.mode === 'session_enforced'"
            :disabled="saving"
            @change="value => setControl(item, Boolean(value))"
          />
        </div>
      </div>
    </section>

    <section class="settings-card">
      <div class="flex items-center gap-2">
        <ShieldCheck class="size-4" />
        <h2 class="m-0">{{ t("access.pending") }}</h2>
      </div>
      <div v-if="!requests.length" class="mt-3 text-sm text-muted-foreground">{{ t("access.noPending") }}</div>
      <div v-for="request in requests" :key="request.id" class="mt-3 flex flex-wrap items-center gap-3 rounded-lg border border-border p-3">
        <div class="min-w-0 flex-1">
          <div class="text-sm font-medium">{{ request.kind }}</div>
          <div class="mt-1 text-xs text-muted-foreground">
            {{ t("access.session") }} {{ request.session_id.slice(0, 8) }} ·
            <template v-if="request.kind === 'full_access'">{{ requestedScope(request) }}</template>
            <template v-else>{{ expiry(request.requested_expires_at) }}</template>
          </div>
          <div v-if="requestDrafts[request.id]" class="mt-3 flex flex-wrap gap-2">
            <template v-if="request.kind === 'full_access'">
              <Select
                v-model:value="requestDrafts[request.id].account_scope"
                class="w-32"
                :options="[
                  { label: 'none', value: 'none' },
                  { label: 'all', value: 'all' },
                  { label: 'selected', value: 'selected' },
                ]"
              />
              <input
                v-model="requestDrafts[request.id].account_ids"
                class="field min-w-56 flex-1"
                :placeholder="t('access.accountIds')"
                :disabled="requestDrafts[request.id].account_scope !== 'selected'"
              />
            </template>
            <input
              v-else
              v-model.number="requestDrafts[request.id].expires_at"
              type="number"
              min="0"
              class="field w-52"
            />
          </div>
        </div>
        <Button size="sm" variant="outline" :disabled="saving" @click="resolve(request, false)">{{ t("access.deny") }}</Button>
        <Button size="sm" :disabled="saving" @click="resolve(request, true)">{{ t("access.approve") }}</Button>
      </div>
    </section>

    <section class="settings-card">
      <h2>{{ t("access.sessions") }}</h2>
      <div v-if="!sessions.length" class="text-sm text-muted-foreground">{{ t("access.noSessions") }}</div>
      <div v-for="session in sessions" :key="session.id" class="mt-3 rounded-lg border border-border p-4">
        <div class="flex flex-wrap items-start justify-between gap-3">
          <div>
            <div class="font-medium">{{ surfaceNames.get(session.surface_id) ?? session.surface_id }} · {{ session.status }}</div>
            <div class="mt-1 font-mono text-xs text-muted-foreground">{{ session.uid }}</div>
          </div>
          <div class="text-right text-xs text-muted-foreground">{{ expiry(session.expires_at) }}</div>
        </div>

        <div v-if="drafts[session.id]" class="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-5">
          <label class="text-xs">
            <span class="mb-1 block text-muted-foreground">{{ t("access.level") }}</span>
            <Select v-model:value="drafts[session.id].access_level" class="w-full" :options="[
              { label: 'read_only', value: 'read_only' },
              { label: 'full_access', value: 'full_access' },
            ]" />
          </label>
          <label class="text-xs">
            <span class="mb-1 block text-muted-foreground">{{ t("access.accountScope") }}</span>
            <Select v-model:value="drafts[session.id].account_scope" class="w-full" :options="[
              { label: 'none', value: 'none' },
              { label: 'all', value: 'all' },
              { label: 'selected', value: 'selected' },
            ]" />
          </label>
          <label class="text-xs">
            <span class="mb-1 block text-muted-foreground">{{ t("access.accountIds") }}</span>
            <input v-model="drafts[session.id].account_ids" class="field" :disabled="drafts[session.id].account_scope !== 'selected'" />
          </label>
          <label class="text-xs">
            <span class="mb-1 block text-muted-foreground">{{ t("access.expiresAt") }}</span>
            <input v-model.number="drafts[session.id].expires_at" type="number" min="0" class="field" />
          </label>
          <label class="text-xs">
            <span class="mb-1 block text-muted-foreground">{{ t("access.label") }}</span>
            <input v-model="drafts[session.id].label" class="field" />
          </label>
        </div>

        <div class="mt-3 flex justify-end gap-2">
          <Button size="sm" variant="outline" :disabled="saving || session.status !== 'active'" @click="revoke(session)">{{ t("access.revoke") }}</Button>
          <Button size="sm" :disabled="saving" @click="saveSession(session)">{{ t("common.save") }}</Button>
        </div>
      </div>
    </section>
  </div>
</template>
