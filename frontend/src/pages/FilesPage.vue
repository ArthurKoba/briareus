<script setup lang="ts">
import { computed, onMounted, ref } from "vue"
import { Modal } from "ant-design-vue"
import { ArrowUp, FolderPlus, RefreshCw, Upload } from "lucide-vue-next"
import { managementApi, type FilesState } from "@/shared/api/management"
import { formatBytes } from "@/shared/lib/format"
import Button from "@/shared/ui/Button.vue"
import DataTable from "@/shared/ui/DataTable.vue"
import PageHeader from "@/shared/ui/PageHeader.vue"

const state = ref<FilesState | null>(null); const loading = ref(false); const error = ref(""); const uploadOpen = ref(false); const mkdirOpen = ref(false); const mkdirName = ref(""); const uploadFile = ref<File | null>(null); const overwrite = ref(false)
const rows = computed(() => state.value?.listing.entries ?? [])
const columns = [{ title: "Name", dataIndex: "name", key: "name" }, { title: "Type", dataIndex: "type", key: "type", width: 110 }, { title: "Size", dataIndex: "size_bytes", key: "size_bytes", width: 120 }, { title: "Actions", key: "actions", width: 180 }]
async function load(path = state.value?.current_path ?? "") { loading.value = true; error.value = ""; try { state.value = await managementApi.files(path) } catch (e) { error.value = e instanceof Error ? e.message : "Unable to load files" } finally { loading.value = false } }
function selectUpload(event: Event) { const input = event.target as HTMLInputElement; uploadFile.value = input.files?.[0] ?? null }
async function upload() { if (!uploadFile.value) return; await managementApi.uploadFile(state.value?.current_path ?? "", uploadFile.value, overwrite.value); uploadOpen.value = false; uploadFile.value = null; await load() }
async function mkdir() { if (!mkdirName.value.trim()) return; await managementApi.mkdir(state.value?.current_path ?? "", mkdirName.value); mkdirOpen.value = false; mkdirName.value = ""; await load() }
async function remove(record: Record<string, unknown>) { const path = String(record.path ?? ""); if (!window.confirm(`Delete ${path}?`)) return; await managementApi.deleteFile(path, record.type === "directory"); await load() }
onMounted(() => load(""))
</script>
<template>
  <div class="space-y-6">
    <PageHeader title="Files" :description="`Workspace /${state?.current_path || ''}`"><Button v-if="state?.current_path" variant="outline" size="sm" @click="load(state.parent_path)"><ArrowUp class="mr-2 size-4" />Up</Button><Button variant="outline" size="sm" @click="load()"><RefreshCw class="mr-2 size-4" />Refresh</Button><Button variant="outline" size="sm" @click="mkdirOpen = true"><FolderPlus class="mr-2 size-4" />New folder</Button><Button size="sm" @click="uploadOpen = true"><Upload class="mr-2 size-4" />Upload</Button></PageHeader>
    <div v-if="state" class="flex flex-wrap gap-5 text-xs text-muted-foreground"><span>{{ state.listing.total }} entries</span><span>{{ formatBytes(state.stats.size_bytes) }} stored</span><span>{{ formatBytes(state.stats.free_bytes) }} free</span></div>
    <p v-if="error" class="text-sm text-destructive">{{ error }}</p>
    <DataTable :columns="columns" :data-source="rows" :loading="loading" row-key="path">
      <template #bodyCell="{ column, record }"><template v-if="column.key === 'name'"><button v-if="record.type === 'directory'" class="font-medium underline underline-offset-4" @click="load(record.path)">{{ record.name }}/</button><span v-else>{{ record.name }}</span></template><template v-else-if="column.key === 'size_bytes'">{{ record.type === 'file' ? formatBytes(record.size_bytes) : '—' }}</template><template v-else-if="column.key === 'actions'"><div class="flex gap-1"><a v-if="record.type === 'file'" class="btn-link" :href="managementApi.fileDownloadUrl(record.path)">Download</a><Button variant="ghost" size="sm" @click="remove(record)">Delete</Button></div></template></template>
    </DataTable>
    <Modal v-model:open="uploadOpen" title="Upload file" @ok="upload"><div class="space-y-3 py-3"><input type="file" @change="selectUpload" /><label class="flex items-center gap-2 text-sm"><input v-model="overwrite" type="checkbox" />Overwrite existing file</label></div></Modal>
    <Modal v-model:open="mkdirOpen" title="Create folder" @ok="mkdir"><label class="block space-y-2 py-3 text-sm"><span>Name</span><input v-model="mkdirName" class="field" @keyup.enter="mkdir" /></label></Modal>
  </div>
</template>
