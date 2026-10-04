<script setup lang="ts">
import DataTable from "@/shared/ui/DataTable.vue"
import type { DataTableColumn } from "./types"

const props = withDefaults(defineProps<{
  columns: DataTableColumn[]
  dataSource: unknown[]
  loading?: boolean
  loadingMore?: boolean
  hasMore?: boolean
  rowKey?: string | ((record: any) => string)
  scrollY?: number
  clickable?: boolean
  framed?: boolean
}>(), {
  loading: false,
  loadingMore: false,
  hasMore: false,
  scrollY: 620,
  clickable: false,
  framed: true,
})

const emit = defineEmits<{
  endReached: []
  rowClick: [record: any]
  scrollPosition: [atTop: boolean]
}>()

function endReached(): void {
  if (!props.loading && !props.loadingMore && props.hasMore) emit("endReached")
}
</script>

<template>
  <div :class="framed ? 'overflow-hidden rounded-xl border border-border/70 bg-card' : ''">
  <DataTable
    :columns="columns"
    :data-source="dataSource"
    :loading="loading || loadingMore"
    :row-key="rowKey"
    virtual
    :scroll-y="scrollY"
    :clickable="clickable"
      :framed="false"
    @end-reached="endReached"
    @row-click="emit('rowClick', $event)"
    @scroll-position="emit('scrollPosition', $event)"
  >
    <template #bodyCell="slotProps"><slot name="bodyCell" v-bind="slotProps" /></template>
  </DataTable>
  </div>
</template>
