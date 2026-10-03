<script setup lang="ts">
import { Table } from "ant-design-vue"
import type { TableProps } from "ant-design-vue"

defineProps<{ columns: TableProps["columns"]; dataSource: unknown[]; loading?: boolean; rowKey?: string | ((record: any) => string); pagination?: false | Record<string, unknown> }>()
</script>
<template>
  <div class="data-table overflow-hidden rounded-xl border border-border bg-card">
    <Table :columns="columns" :data-source="dataSource" :loading="loading" :row-key="rowKey || 'id'" :pagination="pagination === undefined ? { pageSize: 25, showSizeChanger: true } : pagination" size="middle">
      <template #bodyCell="slotProps"><slot name="bodyCell" v-bind="slotProps" /></template>
    </Table>
  </div>
</template>
