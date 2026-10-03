<script setup lang="ts">
import { computed } from "vue"
import { Table } from "ant-design-vue"
import type { TableProps } from "ant-design-vue"
import { uiPreferences } from "@/shared/lib/preferences"
const props=withDefaults(defineProps<{columns:TableProps["columns"];dataSource:unknown[];loading?:boolean;rowKey?:string|((record:any)=>string);pagination?:false|Record<string,unknown>;virtual?:boolean;scrollY?:number}>(),{loading:false,virtual:false,scrollY:560})
const emit=defineEmits<{endReached:[]}>()
const size=computed(()=>uiPreferences.density.value==="compact"?"small":"middle")
function onScroll(event:Event){const target=event.target as HTMLElement;if(target.scrollHeight-target.scrollTop-target.clientHeight<180)emit("endReached")}
</script>
<template><div class="data-table overflow-hidden rounded-xl border border-border bg-card"><Table :columns="columns" :data-source="dataSource" :loading="loading" :row-key="rowKey||'id'" :pagination="pagination===undefined?{pageSize:25,showSizeChanger:true}:pagination" :size="size" :virtual="virtual" :scroll="virtual?{y:scrollY,x:'max-content'}:undefined" @scroll="onScroll"><template #bodyCell="slotProps"><slot name="bodyCell" v-bind="slotProps" /></template></Table></div></template>
