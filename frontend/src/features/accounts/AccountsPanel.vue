<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue"
import { Select, Switch } from "ant-design-vue"
import {
  Check,
  CircleCheck,
  CircleX,
  ExternalLink,
  PlugZap,
  LoaderCircle,
  Pencil,
  Plus,
  RefreshCw,
  Trash2,
  X,
} from "lucide-vue-next"
import { useI18n } from "vue-i18n"

import { managementApi, type AccountPayload, type AccountRecord } from "@/shared/api/management"
import { formatDate } from "@/shared/lib/format"
import { notifications } from "@/shared/notifications/bus"
import { useAccountVerification } from "./model/use-account-verification"
import AppDialog from "@/shared/ui/AppDialog.vue"
import Button from "@/shared/ui/Button.vue"
import DataTable from "@/shared/ui/DataTable.vue"
import PageHeader from "@/shared/ui/PageHeader.vue"

const props = defineProps<{
  title: string
  description: string
  providers: AccountRecord["provider"][]
  defaultProvider?: AccountRecord["provider"]
}>()

const { t } = useI18n()
const rows = ref<AccountRecord[]>([])
const loading = ref(false)
const error = ref("")
const modalOpen = ref(false)
const editing = ref<AccountRecord | null>(null)
const saving = ref(false)
const modalVerified = ref(false)
const modalVerifying = ref(false)
const verification = useAccountVerification(managementApi.verifyAccount)

const initialProvider = props.defaultProvider ?? props.providers[0] ?? "github"
const form = reactive<AccountPayload>({
  alias: "",
  provider: initialProvider,
  auth_type: "github_token",
  base_url: "",
  external_id: "",
  verify_tls: true,
  ca_cert_pem: "",
  enabled: true,
  credential: "",
})

const providerOptions = computed(() => props.providers.map((value) => ({ label: value, value })))
const authOptions = computed(() => ({
  github: [
    { label: "GitHub token", value: "github_token" },
    { label: "GitHub App", value: "github_app" },
  ],
  gitlab: [
    { label: "Private token", value: "private_token" },
    { label: "Bearer token", value: "bearer" },
    { label: "Job token", value: "job_token" },
  ],
  signoz: [{ label: "API key", value: "signoz_api_key" }],
  coolify: [{ label: "API token", value: "coolify_api_token" }],
}[form.provider]))
const showProvider = computed(() => props.providers.length > 1)
const showAuthType = computed(() => authOptions.value.length > 1)
const authLabel = (value: string) => ({
  github_token: "GitHub token",
  github_app: "GitHub App",
  private_token: "Private token",
  bearer: "Bearer token",
  job_token: "Job token",
  signoz_api_key: "API key",
  coolify_api_token: "API token",
}[value] ?? value)

const columns = computed(() => [
  { title: t("accounts.alias"), dataIndex: "alias", key: "alias", width: 180 },
  ...(showAuthType.value ? [{ title: t("accounts.auth"), dataIndex: "auth_type", key: "auth_type", width: 160 }] : []),
  { title: t("accounts.endpoint"), dataIndex: "base_url", key: "base_url" },
  { title: t("common.enabled"), dataIndex: "enabled", key: "enabled", width: 92, align: "center" as const },
  { title: t("accounts.updated"), dataIndex: "updated_at", key: "updated_at", width: 170 },
  { title: "", key: "actions", width: 120, sortable: false, align: "right" as const },
])

function defaults(provider: AccountRecord["provider"]): void {
  form.provider = provider
  form.auth_type = provider === "github"
    ? "github_token"
    : provider === "gitlab"
      ? "private_token"
      : provider === "signoz"
        ? "signoz_api_key"
        : "coolify_api_token"
  if (provider === "gitlab" && !form.base_url) form.base_url = "https://gitlab.com"
}

function newAccount(): void {
  editing.value = null
  modalVerified.value = false
  Object.assign(form, {
    alias: "",
    provider: initialProvider,
    auth_type: "",
    base_url: "",
    external_id: "",
    verify_tls: true,
    ca_cert_pem: "",
    enabled: true,
    credential: "",
  })
  defaults(initialProvider)
  modalOpen.value = true
}

function editAccount(record: AccountRecord): void {
  editing.value = record
  modalVerified.value = false
  Object.assign(form, {
    alias: record.alias,
    provider: record.provider,
    auth_type: record.auth_type,
    base_url: record.base_url || "",
    external_id: record.external_id || "",
    verify_tls: record.verify_tls,
    ca_cert_pem: record.ca_cert_pem || "",
    enabled: record.enabled,
    credential: "",
  })
  modalOpen.value = true
}

async function load(): Promise<void> {
  loading.value = true
  error.value = ""
  try {
    const all = (await managementApi.accounts()).accounts
    rows.value = all.filter((item) => props.providers.includes(item.provider))
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : "Unable to load accounts"
  } finally {
    loading.value = false
  }
}

function verify(record: AccountRecord): Promise<boolean> {
  return verification.verify(record)
}

function verificationLabel(record: AccountRecord): string {
  const result = verification.stateFor(record)
  if (result.status === "loading") return String(t("accounts.checking"))
  if (result.status === "success") return `${t("accounts.connectionVerified")} · ${formatDate(result.checkedAt)}`
  if (result.status === "error") return `${t("accounts.connectionFailed")}: ${result.message}`
  return String(t("accounts.testConnection"))
}

async function verifyCurrent(): Promise<void> {
  if (!editing.value) return
  modalVerifying.value = true
  modalVerified.value = await verify(editing.value)
  modalVerifying.value = false
}

async function save(): Promise<void> {
  if (editing.value && !modalVerified.value) return
  saving.value = true
  try {
    let record: AccountRecord
    if (editing.value) record = await managementApi.updateAccount(editing.value, { ...form })
    else record = await managementApi.createAccount({ ...form })
    modalOpen.value = false
    notifications.success(String(t("notifications.saved")))
    await load()
    if (!editing.value) void verify(record)
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : "Unable to save account"
  } finally {
    saving.value = false
  }
}

async function remove(record: AccountRecord): Promise<void> {
  if (!window.confirm(String(t("accounts.deleteConfirm", { alias: record.alias })))) return
  await managementApi.deleteAccount(record)
  notifications.success(String(t("notifications.deleted")), record.alias)
  await load()
}

onMounted(load)
</script>

<template>
  <div class="space-y-5">
    <PageHeader :title="title" :description="description">
      <Button variant="outline" size="sm" @click="load">
        <RefreshCw class="mr-2 size-4" />{{ t("common.refresh") }}
      </Button>
      <Button size="sm" @click="newAccount">
        <Plus class="mr-2 size-4" />{{ t("accounts.add") }}
      </Button>
    </PageHeader>

    <p v-if="error" class="rounded-lg bg-destructive/10 px-4 py-3 text-sm text-destructive">{{ error }}</p>

    <DataTable :columns="columns" :data-source="rows" :loading="loading" clickable @row-click="editAccount">
      <template #bodyCell="{ column, record, value }">
        <template v-if="column.key === 'alias'">
          <div class="min-w-0">
            <div class="truncate font-medium">{{ record.alias }}</div>
            <div v-if="showProvider" class="mt-0.5 text-[10px] uppercase text-muted-foreground">{{ record.provider }}</div>
          </div>
        </template>
        <template v-else-if="column.key === 'auth_type'">
          <span class="text-xs">{{ authLabel(record.auth_type) }}</span>
        </template>
        <template v-else-if="column.key === 'base_url'">
          <a
            v-if="record.base_url"
            :href="record.base_url"
            target="_blank"
            rel="noreferrer"
            class="inline-flex max-w-full items-center gap-1 truncate text-primary hover:underline"
            data-row-action
            @click.stop
          >
            <span class="truncate">{{ record.base_url }}</span><ExternalLink class="size-3 shrink-0" />
          </a>
          <span v-else>—</span>
        </template>
        <template v-else-if="column.key === 'enabled'">
          <Check v-if="record.enabled" class="mx-auto size-4 text-emerald-500" />
          <X v-else class="mx-auto size-4 text-muted-foreground" />
        </template>
        <template v-else-if="column.key === 'updated_at'">{{ formatDate(record.updated_at) }}</template>
        <template v-else-if="column.key === 'actions'">
          <div class="flex w-full items-center justify-end gap-1" data-row-action @click.stop>
            <button
              type="button"
              class="grid size-7 place-items-center rounded-md transition-colors hover:bg-accent active:bg-accent/80 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-wait disabled:opacity-70"
              :title="verificationLabel(record)"
              :aria-label="verificationLabel(record)"
              :aria-busy="verification.stateFor(record).status === 'loading'"
              :disabled="verification.stateFor(record).status === 'loading'"
              @click.stop="verify(record)"
            >
              <LoaderCircle v-if="verification.stateFor(record).status === 'loading'" class="size-4 animate-spin" />
              <CircleCheck v-else-if="verification.stateFor(record).status === 'success'" class="size-4 text-emerald-500" />
              <CircleX v-else-if="verification.stateFor(record).status === 'error'" class="size-4 text-destructive" />
              <PlugZap v-else class="size-4 text-muted-foreground" />
            </button>
            <button type="button" class="grid size-7 place-items-center rounded-md hover:bg-accent" :title="String(t('common.edit'))" @click.stop="editAccount(record)"><Pencil class="size-4" /></button>
            <button type="button" class="grid size-7 place-items-center rounded-md text-muted-foreground hover:bg-destructive/10 hover:text-destructive" :title="String(t('common.delete'))" @click.stop="remove(record)"><Trash2 class="size-4" /></button>
            <span class="sr-only" role="status">{{ verificationLabel(record) }}</span>
          </div>
        </template>
        <template v-else><span class="truncate">{{ value ?? "—" }}</span></template>
      </template>
    </DataTable>

    <AppDialog
      :open="modalOpen"
      :title="editing ? `${t('accounts.editTitle')}: ${editing.alias}` : t('accounts.addTitle')"
      width="700px"
      :close-label="String(t('common.close'))"
      @close="modalOpen = false"
    >
      <div class="grid gap-4 sm:grid-cols-2">
        <label class="space-y-1 text-sm"><span>{{ t("accounts.alias") }}</span><input v-model="form.alias" class="field" /></label>
        <label v-if="showProvider" class="space-y-1 text-sm"><span>{{ t("common.provider") }}</span><Select v-model:value="form.provider" class="w-full" :options="providerOptions" :disabled="Boolean(editing)" @change="defaults(form.provider)" /></label>
        <label v-if="showAuthType" class="space-y-1 text-sm"><span>{{ t("accounts.authType") }}</span><Select v-model:value="form.auth_type" class="w-full" :options="authOptions" /></label>
        <label class="space-y-1 text-sm" :class="!showAuthType && !showProvider ? 'sm:col-span-2' : ''"><span>{{ t("accounts.credential") }} {{ editing ? `(${t('accounts.leaveBlank')})` : "" }}</span><input v-model="form.credential" type="password" autocomplete="new-password" class="field" /></label>
        <label v-if="form.provider !== 'github'" class="space-y-1 text-sm sm:col-span-2"><span>{{ t("accounts.baseUrl") }}</span><input v-model="form.base_url" class="field" placeholder="https://…" /></label>
        <label v-if="form.provider === 'github' && form.auth_type === 'github_app'" class="space-y-1 text-sm sm:col-span-2"><span>{{ t("accounts.appId") }}</span><input v-model="form.external_id" class="field" /></label>
        <label v-if="form.provider !== 'github'" class="flex items-center gap-3 text-sm"><Switch v-model:checked="form.verify_tls" /><span>{{ t("accounts.verifyTls") }}</span></label>
        <label class="flex items-center gap-3 text-sm"><Switch v-model:checked="form.enabled" /><span>{{ t("common.enabled") }}</span></label>
        <label v-if="form.provider !== 'github'" class="space-y-1 text-sm sm:col-span-2"><span>{{ t("accounts.customCa") }}</span><textarea v-model="form.ca_cert_pem" class="field min-h-24 font-mono text-xs" /></label>
      </div>

      <div v-if="editing && verification.stateFor(editing).status === 'error'" class="mt-3 text-sm text-destructive" role="status">{{ verificationLabel(editing) }}</div>

      <template #footer>
        <Button variant="ghost" @click="modalOpen = false">{{ t("common.cancel") }}</Button>
        <Button v-if="editing" variant="outline" :disabled="modalVerifying" @click="verifyCurrent">
          <LoaderCircle v-if="modalVerifying" class="mr-2 size-4 animate-spin" />
          <CircleCheck v-else-if="modalVerified" class="mr-2 size-4 text-emerald-500" />
          <PlugZap v-else class="mr-2 size-4" />
          {{ t("common.test") }}
        </Button>
        <Button :disabled="saving || Boolean(editing && !modalVerified)" @click="save">
          {{ editing ? t("common.confirm") : t("common.add") }}
        </Button>
      </template>
    </AppDialog>
  </div>
</template>
