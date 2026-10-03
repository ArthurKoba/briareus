<script setup lang="ts">
import { computed, ref } from "vue"
import {
  createSortedRowModel,
  rowSortingFeature,
  sortFn_alphanumeric,
  tableFeatures,
  useTable,
  type ColumnDef,
} from "@tanstack/vue-table"
import { useVirtualizer } from "@tanstack/vue-virtual"
import { ArrowDown, ArrowUp, ChevronsUpDown } from "lucide-vue-next"

import { uiPreferences } from "@/shared/lib/preferences"

export interface DataTableColumn {
  title?: string
  dataIndex?: string
  key?: string
  width?: number
  sortable?: boolean
  align?: "left" | "center" | "right"
}

const props = withDefaults(defineProps<{
  columns: DataTableColumn[]
  dataSource: unknown[]
  loading?: boolean
  rowKey?: string | ((record: any) => string)
  pagination?: false | Record<string, unknown>
  virtual?: boolean
  scrollY?: number
}>(), {
  loading: false,
  virtual: false,
  scrollY: 560,
})

const emit = defineEmits<{ endReached: [] }>()
const scrollElement = ref<HTMLElement | null>(null)

const features = tableFeatures({
  rowSortingFeature,
  sortedRowModel: createSortedRowModel(),
  sortFns: { alphanumeric: sortFn_alphanumeric },
})

const tableColumns = computed<ColumnDef<Record<string, unknown>>[]>(() =>
  props.columns.map((column, index) => ({
    id: column.key ?? column.dataIndex ?? `column-${index}`,
    accessorKey: column.dataIndex,
    header: column.title ?? "",
    enableSorting: column.sortable ?? Boolean(column.dataIndex && column.key !== "actions"),
    sortFn: "alphanumeric",
    meta: { legacy: column },
  })),
)

const data = computed(() => props.dataSource as Record<string, unknown>[])
const table = useTable({ features, columns: tableColumns, data })
const rows = computed(() => table.getRowModel().rows)
const rowHeight = computed(() => uiPreferences.density.value === "compact" ? 32 : 40)
const columnTemplate = computed(() => props.columns.map((column) => {
  if (column.width) return `${column.width}px`
  if (column.key === "actions") return "minmax(104px,auto)"
  return "minmax(120px,1fr)"
}).join(" "))

const rowVirtualizer = useVirtualizer(computed(() => ({
  count: props.virtual ? rows.value.length : 0,
  getScrollElement: () => scrollElement.value,
  estimateSize: () => rowHeight.value,
  getItemKey: (index: number) => rows.value[index]?.id ?? index,
  overscan: 10,
})))

const virtualRows = computed(() => rowVirtualizer.value.getVirtualItems())
const totalSize = computed(() => rowVirtualizer.value.getTotalSize())

function originalKey(record: Record<string, unknown>, index: number): string {
  if (typeof props.rowKey === "function") return props.rowKey(record)
  if (typeof props.rowKey === "string") return String(record[props.rowKey] ?? index)
  return String(record.id ?? record.key ?? index)
}

function cellValue(record: Record<string, unknown>, column: DataTableColumn): unknown {
  return column.dataIndex ? record[column.dataIndex] : undefined
}

function sortDirection(columnId: string): false | "asc" | "desc" {
  return table.getColumn(columnId)?.getIsSorted() ?? false
}

function toggleSort(columnId: string): void {
  const column = table.getColumn(columnId)
  if (column?.getCanSort()) column.toggleSorting()
}

function onScroll(event: Event): void {
  const target = event.target as HTMLElement
  if (target.scrollHeight - target.scrollTop - target.clientHeight < 320) emit("endReached")
}
</script>

<template>
  <div class="ts-table overflow-hidden rounded-xl border border-border/70 bg-card shadow-[0_1px_2px_rgb(0_0_0_/_0.03)]">
    <div
      ref="scrollElement"
      class="relative overflow-auto"
      :style="{ maxHeight: `${scrollY}px` }"
      @scroll="onScroll"
    >
      <div
        class="ts-table-head sticky top-0 z-10 grid min-w-full border-b border-border/70 bg-muted/80 backdrop-blur"
        :style="{ gridTemplateColumns: columnTemplate }"
      >
        <button
          v-for="(column, index) in columns"
          :key="column.key ?? column.dataIndex ?? index"
          type="button"
          class="flex min-w-0 items-center gap-1.5 px-3 text-left text-[11px] font-semibold uppercase tracking-[0.06em] text-muted-foreground"
          :class="[
            column.align === 'right' && 'justify-end text-right',
            column.align === 'center' && 'justify-center text-center',
            (column.sortable ?? Boolean(column.dataIndex && column.key !== 'actions')) && 'cursor-pointer hover:text-foreground',
          ]"
          :style="{ height: `${rowHeight}px` }"
          @click="toggleSort(String(column.key ?? column.dataIndex ?? `column-${index}`))"
        >
          <span class="truncate">{{ column.title }}</span>
          <template v-if="column.sortable ?? Boolean(column.dataIndex && column.key !== 'actions')">
            <ArrowUp v-if="sortDirection(String(column.key ?? column.dataIndex ?? `column-${index}`)) === 'asc'" class="size-3 shrink-0" />
            <ArrowDown v-else-if="sortDirection(String(column.key ?? column.dataIndex ?? `column-${index}`)) === 'desc'" class="size-3 shrink-0" />
            <ChevronsUpDown v-else class="size-3 shrink-0 opacity-40" />
          </template>
        </button>
      </div>

      <div v-if="loading && !dataSource.length" class="grid h-32 place-items-center text-sm text-muted-foreground">
        Loading…
      </div>
      <div v-else-if="!dataSource.length" class="grid h-28 place-items-center text-sm text-muted-foreground">
        —
      </div>

      <template v-else-if="virtual">
        <div class="relative min-w-full" :style="{ height: `${totalSize}px` }">
          <div
            v-for="virtualRow in virtualRows"
            :key="virtualRow.key"
            class="ts-table-row absolute left-0 grid w-full border-b border-border/40 text-[12px] hover:bg-accent/45"
            :style="{
              gridTemplateColumns: columnTemplate,
              height: `${virtualRow.size}px`,
              transform: `translateY(${virtualRow.start}px)`,
            }"
          >
            <div
              v-for="(column, columnIndex) in columns"
              :key="column.key ?? column.dataIndex ?? columnIndex"
              class="flex min-w-0 items-center px-3"
              :class="[
                column.align === 'right' && 'justify-end text-right',
                column.align === 'center' && 'justify-center text-center',
              ]"
            >
              <slot
                name="bodyCell"
                :column="column"
                :record="rows[virtualRow.index]!.original"
                :value="cellValue(rows[virtualRow.index]!.original, column)"
                :row-index="virtualRow.index"
              >
                <span class="truncate">{{ cellValue(rows[virtualRow.index]!.original, column) ?? "—" }}</span>
              </slot>
            </div>
          </div>
        </div>
      </template>

      <div v-else class="min-w-full">
        <div
          v-for="(row, rowIndex) in rows"
          :key="originalKey(row.original, rowIndex)"
          class="ts-table-row grid border-b border-border/40 text-[12px] last:border-b-0 hover:bg-accent/45"
          :style="{ gridTemplateColumns: columnTemplate, minHeight: `${rowHeight}px` }"
        >
          <div
            v-for="(column, columnIndex) in columns"
            :key="column.key ?? column.dataIndex ?? columnIndex"
            class="flex min-w-0 items-center px-3"
            :class="[
              column.align === 'right' && 'justify-end text-right',
              column.align === 'center' && 'justify-center text-center',
            ]"
          >
            <slot
              name="bodyCell"
              :column="column"
              :record="row.original"
              :value="cellValue(row.original, column)"
              :row-index="rowIndex"
            >
              <span class="truncate">{{ cellValue(row.original, column) ?? "—" }}</span>
            </slot>
          </div>
        </div>
      </div>

      <div v-if="loading && dataSource.length" class="sticky bottom-0 flex h-7 items-center justify-center border-t border-border/50 bg-card/90 text-[11px] text-muted-foreground backdrop-blur">
        Loading…
      </div>
    </div>
  </div>
</template>
