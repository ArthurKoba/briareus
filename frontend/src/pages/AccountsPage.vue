<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue"
import { Modal, Select, Switch, Tag } from "ant-design-vue"
import { Plus, RefreshCw } from "lucide-vue-next"
import { managementApi, type AccountPayload, type AccountRecord } from "@/shared/api/management"
import { formatDate } from "@/shared/lib/format"
import Button from "@/shared/ui/Button.vue"
import DataTable from "@/shared/ui/DataTable.vue"
import PageHeader from "@/shared/ui/PageHeader.vue"

const rows = ref<AccountRecord[]>([])
const loading = ref(false)
const error = ref("")
const modalOpen = ref(false)
const editing = ref<AccountRecord | null>(null)
const saving = ref(false)
const verifyResult = ref("")

const form = reactive<AccountPayload>({ alias: "", provider: "github", auth_type: "github_token", base_url: "", external_id: "", verify_tls: true, ca_cert_pem: "", enabled: true, credential: "" })
const providerOptions = ["github", "gitlab", "signoz", "coolify"].map(value => ({ label: value, value }))
const authOptions = computed(() => ({
  github: [{ label: "GitHub token", value: "github_token" }, { label: "GitHub App", value: "github_app" }],
  gitlab: [{ label: "Private token", value: "private_token" }, { label: "Bearer", value: "bearer" }, { label: "Job token", value: "job_token" }],
  signoz: [{ label: "SigNoz API key", value: "signoz_api_key" }],
  coolify: [{ label: "Coolify API token", value: "coolify_api_token" }],
}[form.provider]))
const columns = [
  { title: "Alias", dataIndex: "alias", key: "alias" }, { title: "Provider", dataIndex: "provider", key: "provider", width: 120 },
  { title: "Auth", dataIndex: "auth_type", key: "auth_type", width: 150 }, { title: "Endpoint", dataIndex: "base_url", key: "base_url" },
  { title: "Enabled", dataIndex: "enabled", key: "enabled", width: 100 }, { title: "Updated", dataIndex: "updated_at", key: "updated_at", width: 180 },
  { title: "Actions", key: "actions", width: 230 },
]

function defaults(provider: AccountRecord["provider"]): void {
  form.provider = provider
  form.auth_type = provider === "github" ? "github_token" : provider === "gitlab" ? "private_token" : provider === "signoz" ? "signoz_api_key" : "coolify_api_token"
  if (provider === "gitlab" && !form.base_url) form.base_url = "https://gitlab.com"
}
function newAccount() { editing.value = null; Object.assign(form, { alias: "", provider: "github", auth_type: "github_token", base_url: "", external_id: "", verify_tls: true, ca_cert_pem: "", enabled: true, credential: "" }); modalOpen.value = true }
function editAccount(record: any) { editing.value = record; Object.assign(form, { alias: record.alias, provider: record.provider, auth_type: record.auth_type, base_url: record.base_url || "", external_id: record.external_id || "", verify_tls: record.verify_tls, ca_cert_pem: record.ca_cert_pem || "", enabled: record.enabled, credential: "" }); modalOpen.value = true }
async function load() { loading.value = true; error.value = ""; try { rows.value = (await managementApi.accounts()).accounts } catch (e) { error.value = e instanceof Error ? e.message : "Unable to load accounts" } finally { loading.value = false } }
async function save() { saving.value = true; error.value = ""; try { if (editing.value) await managementApi.updateAccount(editing.value, { ...form }); else await managementApi.createAccount({ ...form }); modalOpen.value = false; await load() } catch (e) { error.value = e instanceof Error ? e.message : "Unable to save account" } finally { saving.value = false } }
async function verify(record: any) { verifyResult.value = "Checking…"; try { const result = await managementApi.verifyAccount(record); verifyResult.value = `${record.alias}: ${JSON.stringify(result)}` } catch (e) { verifyResult.value = `${record.alias}: ${e instanceof Error ? e.message : 'verification failed'}` } }
async function remove(record: any) { if (!window.confirm(`Delete ${record.alias}?`)) return; await managementApi.deleteAccount(record); await load() }
onMounted(load)
</script>
<template>
  <div class="space-y-6">
    <PageHeader title="Accounts" description="Credentials stay server-side; the UI never receives stored secrets.">
      <Button variant="outline" size="sm" @click="load"><RefreshCw class="mr-2 size-4" />Refresh</Button><Button size="sm" @click="newAccount"><Plus class="mr-2 size-4" />Add account</Button>
    </PageHeader>
    <p v-if="error" class="rounded-lg bg-destructive/10 px-4 py-3 text-sm text-destructive">{{ error }}</p>
    <p v-if="verifyResult" class="rounded-lg border border-border bg-muted px-4 py-3 text-xs font-mono">{{ verifyResult }}</p>
    <DataTable :columns="columns" :data-source="rows" :loading="loading">
      <template #bodyCell="{ column, record }">
        <template v-if="column.key === 'provider'"><Tag>{{ record.provider }}</Tag></template>
        <template v-else-if="column.key === 'enabled'"><Tag :color="record.enabled ? 'green' : 'default'">{{ record.enabled ? 'enabled' : 'disabled' }}</Tag></template>
        <template v-else-if="column.key === 'updated_at'">{{ formatDate(record.updated_at) }}</template>
        <template v-else-if="column.key === 'actions'"><div class="flex gap-1"><Button variant="ghost" size="sm" @click="verify(record)">Test</Button><Button variant="ghost" size="sm" @click="editAccount(record)">Edit</Button><Button variant="ghost" size="sm" @click="remove(record)">Delete</Button></div></template>
      </template>
    </DataTable>

    <Modal v-model:open="modalOpen" :title="editing ? `Edit ${editing.alias}` : 'Add account'" :confirm-loading="saving" width="680px" @ok="save">
      <div class="grid gap-4 py-3 sm:grid-cols-2">
        <label class="space-y-1 text-sm"><span>Alias</span><input v-model="form.alias" class="field" /></label>
        <label class="space-y-1 text-sm"><span>Provider</span><Select v-model:value="form.provider" class="w-full" :options="providerOptions" :disabled="Boolean(editing)" @change="defaults(form.provider)" /></label>
        <label class="space-y-1 text-sm"><span>Auth type</span><Select v-model:value="form.auth_type" class="w-full" :options="authOptions" /></label>
        <label class="space-y-1 text-sm"><span>Credential {{ editing ? '(leave blank to keep)' : '' }}</span><input v-model="form.credential" type="password" autocomplete="new-password" class="field" /></label>
        <label v-if="form.provider !== 'github'" class="space-y-1 text-sm sm:col-span-2"><span>Base URL</span><input v-model="form.base_url" class="field" placeholder="https://…" /></label>
        <label v-if="form.provider === 'github' && form.auth_type === 'github_app'" class="space-y-1 text-sm sm:col-span-2"><span>GitHub App ID</span><input v-model="form.external_id" class="field" /></label>
        <label v-if="form.provider !== 'github'" class="flex items-center gap-3 text-sm"><Switch v-model:checked="form.verify_tls" /><span>Verify TLS</span></label>
        <label class="flex items-center gap-3 text-sm"><Switch v-model:checked="form.enabled" /><span>Enabled</span></label>
        <label v-if="form.provider !== 'github'" class="space-y-1 text-sm sm:col-span-2"><span>Custom CA PEM</span><textarea v-model="form.ca_cert_pem" class="field min-h-24 font-mono text-xs" /></label>
      </div>
    </Modal>
  </div>
</template>
