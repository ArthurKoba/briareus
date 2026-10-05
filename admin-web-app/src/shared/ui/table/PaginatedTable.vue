<script setup lang="ts">
import { computed } from "vue"
import { ChevronLeft, ChevronRight } from "lucide-vue-next"
import { Select } from "ant-design-vue"

import Button from "@/shared/ui/Button.vue"
import DataTable from "@/shared/ui/DataTable.vue"
import type { DataTableColumn } from "./types"

const props = withDefaults(defineProps<{
  columns: DataTableColumn[]
  dataSource: readonly unknown[]
  page: number
  pageSize: number
  totalRows: number
  pageSizeOptions?: number[]
  loading?: boolean
  rowKey?: string | ((record: any) => string)
  scrollY?: number
  clickable?: boolean
}>(), {
  pageSizeOptions: () => [25, 50, 100],
  loading: false,
  scrollY: 620,
  clickable: false,
})

const emit = defineEmits<{
  "update:page": [value: number]
  "update:pageSize": [value: number]
  rowClick: [record: any]
}>()

const pageCount = computed(() => Math.max(1, Math.ceil(props.totalRows / Math.max(props.pageSize, 1))))
const canPrevious = computed(() => props.page > 1 && !props.loading)
const canNext = computed(() => props.page < pageCount.value && !props.loading)
const pageSizeSelect = computed(() => String(props.pageSize))

function setPageSize(value: string): void {
  emit("update:pageSize", Number(value))
  emit("update:page", 1)
}
</script>

<template>
  <div class="overflow-hidden rounded-xl border border-border/70 bg-card">
    <DataTable
      class="border-0 shadow-none"
      :columns="columns"
      :data-source="dataSource"
      :loading="loading"
      :row-key="rowKey"
      :scroll-y="scrollY"
      :clickable="clickable"
      :framed="false"
      @row-click="emit('rowClick', $event)"
    >
      <template #bodyCell="slotProps"><slot name="bodyCell" v-bind="slotProps" /></template>
    </DataTable>
    <div class="flex flex-wrap items-center justify-between gap-3 border-t border-border/70 bg-muted/20 px-3 py-2 text-xs text-muted-foreground">
      <div class="flex items-center gap-2">
        <span>{{ totalRows }}</span>
        <Select :value="pageSizeSelect" class="w-20" size="small" :options="pageSizeOptions.map(value => ({ label: String(value), value: String(value) }))" @change="setPageSize(String($event))" />
      </div>
      <div class="flex items-center gap-2">
        <span>{{ page }} / {{ pageCount }}</span>
        <Button variant="outline" size="icon" :disabled="!canPrevious" @click="emit('update:page', page - 1)"><ChevronLeft class="size-4" /></Button>
        <Button variant="outline" size="icon" :disabled="!canNext" @click="emit('update:page', page + 1)"><ChevronRight class="size-4" /></Button>
      </div>
    </div>
  </div>
</template>
