<script setup lang="ts">
import { computed } from "vue"
import { Tag } from "ant-design-vue"
import { useI18n } from "vue-i18n"
import AccountsPanel from "@/features/accounts/AccountsPanel.vue"
import DataTable from "@/shared/ui/DataTable.vue"
import PageHeader from "@/shared/ui/PageHeader.vue"
import StatCard from "@/shared/ui/StatCard.vue"
import { frontendTelemetry } from "@/shared/telemetry/client"
import { eventBus } from "@/shared/events/bus"
import { runtimeConfig } from "@/shared/config/runtime"
import { formatDate } from "@/shared/lib/format"
const {t}=useI18n();const events=computed(()=>frontendTelemetry.events.slice(0,250));const cols=[{title:t('telemetry.time'),dataIndex:'occurredAt',key:'occurredAt',width:180},{title:t('telemetry.event'),dataIndex:'name',key:'name'},{title:t('telemetry.route'),dataIndex:'route',key:'route'},{title:t('telemetry.duration'),dataIndex:'durationMs',key:'durationMs',width:120},{title:t('telemetry.level'),dataIndex:'level',key:'level',width:100}]
</script>
<template><div class="space-y-8"><AccountsPanel :title="t('observability.title')" :description="t('observability.description')" :providers="['signoz','coolify']" default-provider="signoz"/><section class="space-y-4"><PageHeader :title="t('telemetry.title')" :description="runtimeConfig.telemetry.enabled?runtimeConfig.telemetry.endpoint:t('telemetry.pending')"/><div class="grid gap-4 sm:grid-cols-3"><StatCard :label="t('telemetry.enabled')" :value="runtimeConfig.telemetry.enabled?t('common.enabled'):t('common.disabled')" :hint="runtimeConfig.telemetry.endpoint"/><StatCard :label="t('settings.eventBus')" :value="eventBus.state.status" :hint="`${eventBus.state.subscriptions} ${t('common.subscriptions')}`"/><StatCard :label="t('telemetry.event')" :value="events.length" :hint="t('telemetry.localBuffer')"/></div><DataTable :columns="cols" :data-source="events" row-key="id" :pagination="false" virtual :scroll-y="420"><template #bodyCell="{column,record}"><template v-if="column.key==='occurredAt'">{{formatDate(record.occurredAt)}}</template><template v-else-if="column.key==='durationMs'">{{record.durationMs===undefined?'—':`${Number(record.durationMs).toFixed(1)} ms`}}</template><template v-else-if="column.key==='level'"><Tag :color="record.level==='error'?'red':record.level==='warn'?'orange':record.level==='info'?'blue':'default'">{{record.level}}</Tag></template></template></DataTable></section></div></template>
