<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue"
import { Modal, Switch, Tag } from "ant-design-vue"
import { Radio, RefreshCw, Trash2 } from "lucide-vue-next"
import { useI18n } from "vue-i18n"
import { managementApi, type InvocationRecord } from "@/shared/api/management"
import { eventBus, type BusEvent } from "@/shared/events/bus"
import { notifications } from "@/shared/notifications/bus"
import { formatDate } from "@/shared/lib/format"
import Button from "@/shared/ui/Button.vue"
import DataTable from "@/shared/ui/DataTable.vue"
import PageHeader from "@/shared/ui/PageHeader.vue"

const {t}=useI18n()
const rows=ref<InvocationRecord[]>([]),loading=ref(false),error=ref(""),selected=ref<InvocationRecord|null>(null),limit=ref(250),followLive=ref(true),pending=ref<InvocationRecord[]>([])
let unsubscribe:undefined|(()=>void)
const columns=[{title:"Time",dataIndex:"occurred_at",key:"occurred_at",width:180},{title:"Module",dataIndex:"module",key:"module",width:110},{title:"Tool",dataIndex:"tool",key:"tool",width:260},{title:"Status",dataIndex:"status",key:"status",width:100},{title:"Duration",dataIndex:"duration_ms",key:"duration_ms",width:110},{title:"Provider",dataIndex:"provider",key:"provider",width:120},{title:"Actions",key:"actions",width:130}]
const errorCount=computed(()=>rows.value.filter(item=>item.status==="error").length)
const live=computed(()=>eventBus.state.status==="connected")
function merge(item:InvocationRecord){const i=rows.value.findIndex(row=>row.id===item.id);if(i>=0)rows.value.splice(i,1,item);else rows.value.unshift(item);if(rows.value.length>1000)rows.value.length=1000}
function handle(event:BusEvent){if(event.type!=="item")return;const item=event.data as InvocationRecord;if(followLive.value)merge(item);else if(!pending.value.some(row=>row.id===item.id))pending.value.unshift(item)}
function applyPending(){for(const item of pending.value.slice().reverse())merge(item);pending.value=[];followLive.value=true}
async function load(next=limit.value){loading.value=true;error.value="";try{limit.value=next;rows.value=(await managementApi.calls(next)).events}catch(e){error.value=e instanceof Error?e.message:"Unable to load calls"}finally{loading.value=false}}
async function loadMore(){if(loading.value||limit.value>=1000||rows.value.length<limit.value)return;await load(Math.min(1000,limit.value+250))}
function inspect(item:any){selected.value=item as InvocationRecord}
async function clearAll(){if(!window.confirm("Delete all MCP call logs?"))return;const result=await managementApi.clearCalls();rows.value=[];pending.value=[];notifications.success(String(t("notifications.deleted")),`${result.deleted} MCP calls`)}
async function remove(item:any){await managementApi.deleteCall(item.id);rows.value=rows.value.filter(row=>row.id!==item.id);notifications.success(String(t("notifications.deleted")))}
onMounted(async()=>{await load();unsubscribe=eventBus.subscribe("mcp.calls",handle)})
onBeforeUnmount(()=>unsubscribe?.())
</script>
<template><div class="space-y-6"><PageHeader :title="t('nav.calls')" description="Realtime invocation audit stream and payload inspection."><span class="inline-flex items-center gap-1.5 text-xs" :class="live?'text-emerald-500':'text-muted-foreground'"><Radio class="size-3.5"/>{{eventBus.state.status}}</span><label class="inline-flex items-center gap-2 text-xs text-muted-foreground"><Switch v-model:checked="followLive" size="small"/>Follow live</label><Button v-if="pending.length" size="sm" @click="applyPending">{{pending.length}} new</Button><Button variant="outline" size="sm" @click="load()"><RefreshCw class="mr-2 size-4"/>{{t('common.refresh')}}</Button><Button variant="destructive" size="sm" @click="clearAll"><Trash2 class="mr-2 size-4"/>Clear all</Button></PageHeader><div class="flex gap-3 text-xs text-muted-foreground"><span>{{rows.length}} loaded</span><span>{{errorCount}} errors</span><span>limit {{limit}}</span></div><p v-if="error" class="text-sm text-destructive">{{error}}</p><DataTable :columns="columns" :data-source="rows" :loading="loading" :pagination="false" virtual :scroll-y="620" @end-reached="loadMore"><template #bodyCell="{column,record}"><template v-if="column.key==='occurred_at'">{{formatDate(record.occurred_at)}}</template><template v-else-if="column.key==='status'"><Tag :color="record.status==='success'?'green':'red'">{{record.status}}</Tag></template><template v-else-if="column.key==='duration_ms'">{{Number(record.duration_ms).toFixed(1)}} ms</template><template v-else-if="column.key==='actions'"><div class="flex gap-1"><Button variant="ghost" size="sm" @click="inspect(record)">Inspect</Button><Button variant="ghost" size="sm" @click="remove(record)">{{t('common.delete')}}</Button></div></template></template></DataTable><Modal :open="Boolean(selected)" title="MCP Call" :footer="null" width="860px" @cancel="selected=null"><div v-if="selected" class="space-y-4 text-sm"><div class="grid gap-3 sm:grid-cols-2"><div><span class="text-muted-foreground">Tool</span><div class="font-medium">{{selected.tool}}</div></div><div><span class="text-muted-foreground">Request ID</span><div class="break-all font-mono text-xs">{{selected.request_id||'—'}}</div></div></div><div v-for="[label,value] in [['Arguments',selected.arguments_json],['Result',selected.result_json],['Error',selected.error_message]]" :key="label"><div class="mb-1 text-xs font-medium uppercase text-muted-foreground">{{label}}</div><pre class="max-h-64 overflow-auto rounded-lg bg-muted p-3 text-xs whitespace-pre-wrap">{{value||'—'}}</pre></div></div></Modal></div></template>
