<script setup lang="ts">
import { onMounted, ref } from "vue"
import { Tag } from "ant-design-vue"
import { RefreshCw } from "lucide-vue-next"
import { useI18n } from "vue-i18n"
import { adminApi, type OAuthRecord } from "@/shared/api/admin"
import { formatDate } from "@/shared/lib/format"
import Button from "@/shared/ui/Button.vue"
import DataTable from "@/shared/ui/DataTable.vue"
import PageHeader from "@/shared/ui/PageHeader.vue"
const {t}=useI18n();const rows=ref<OAuthRecord[]>([]),loading=ref(false),error=ref("")
const columns=[{title:t('common.status'),dataIndex:'status',key:'status',width:100},{title:t('oauth.surface'),dataIndex:'resource',key:'resource'},{title:t('oauth.login'),dataIndex:'login',key:'login',width:150},{title:t('oauth.client'),dataIndex:'client_name',key:'client_name',width:180},{title:t('oauth.lastUsed'),dataIndex:'last_used_at',key:'last_used_at',width:180},{title:t('oauth.accessExpires'),dataIndex:'access_expires_at',key:'access_expires_at',width:180},{title:t('oauth.lastEvent'),dataIndex:'last_event',key:'last_event',width:180}]
function dateValue(record:any,key:string){return formatDate(record[key])}
async function load(){loading.value=true;error.value='';try{rows.value=(await adminApi.oauthSessions(1000)).sessions}catch(e){error.value=e instanceof Error?e.message:'Unable to load OAuth sessions'}finally{loading.value=false}}
onMounted(load)
</script>
<template><div class="space-y-6"><PageHeader :title="t('nav.oauth')" :description="t('oauth.description')"><Button variant="outline" size="sm" @click="load"><RefreshCw class="mr-2 size-4"/>{{t('common.refresh')}}</Button></PageHeader><p v-if="error" class="text-sm text-destructive">{{error}}</p><DataTable :columns="columns" :data-source="rows" :loading="loading" :pagination="false" virtual :scroll-y="600"><template #bodyCell="{column,record,value}"><template v-if="column.key==='status'"><Tag :color="record.status==='active'?'green':record.status==='revoked'?'default':'red'">{{record.status}}</Tag></template><template v-else-if="column.key==='last_used_at'||column.key==='access_expires_at'">{{dateValue(record,String(column.key))}}</template><template v-else-if="column.key==='client_name'">{{record.client_name||record.client_id||'—'}}</template><template v-else><span class="truncate">{{value ?? '—'}}</span></template></template></DataTable></div></template>
