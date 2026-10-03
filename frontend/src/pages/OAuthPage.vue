<script setup lang="ts">
import { onMounted, ref } from "vue"
import { Tag } from "ant-design-vue"
import { RefreshCw } from "lucide-vue-next"
import { managementApi, type OAuthRecord } from "@/shared/api/management"
import { formatDate } from "@/shared/lib/format"
import Button from "@/shared/ui/Button.vue"
import DataTable from "@/shared/ui/DataTable.vue"
import PageHeader from "@/shared/ui/PageHeader.vue"

const rows = ref<OAuthRecord[]>([]); const loading = ref(false); const error = ref("")
const columns = [
  { title: "Status", dataIndex: "status", key: "status", width: 100 }, { title: "Surface", dataIndex: "resource", key: "resource" },
  { title: "Login", dataIndex: "login", key: "login", width: 150 }, { title: "Client", dataIndex: "client_name", key: "client_name", width: 180 },
  { title: "Last used", dataIndex: "last_used_at", key: "last_used_at", width: 180 }, { title: "Access expires", dataIndex: "access_expires_at", key: "access_expires_at", width: 180 },
  { title: "Last event", dataIndex: "last_event", key: "last_event", width: 180 },
]
function dateValue(record: any, key: string): string { return formatDate(record[key]) }
async function load() { loading.value = true; error.value = ""; try { rows.value = (await managementApi.oauthSessions()).sessions } catch (e) { error.value = e instanceof Error ? e.message : "Unable to load OAuth sessions" } finally { loading.value = false } }
onMounted(load)
</script>
<template><div class="space-y-6"><PageHeader title="OAuth Sessions" description="Observed authorization and refresh-token lifecycle."><Button variant="outline" size="sm" @click="load"><RefreshCw class="mr-2 size-4" />Refresh</Button></PageHeader><p v-if="error" class="text-sm text-destructive">{{ error }}</p><DataTable :columns="columns" :data-source="rows" :loading="loading"><template #bodyCell="{ column, record }"><template v-if="column.key === 'status'"><Tag :color="record.status === 'active' ? 'green' : record.status === 'revoked' ? 'default' : 'red'">{{ record.status }}</Tag></template><template v-else-if="column.key === 'last_used_at' || column.key === 'access_expires_at'">{{ dateValue(record, String(column.key)) }}</template><template v-else-if="column.key === 'client_name'">{{ record.client_name || record.client_id || '—' }}</template></template></DataTable></div></template>
