<script setup lang="ts">
defineProps<{
  modelValue: string
  items: Array<{ id: string; label: string; description?: string; badge?: string | number }>
}>()
const emit = defineEmits<{ "update:modelValue": [value: string] }>()
</script>

<template>
  <div class="section-tabs flex min-w-0 gap-1 overflow-x-auto rounded-lg border border-border/70 bg-muted/35 p-1">
    <button
      v-for="item in items"
      :key="item.id"
      type="button"
      class="flex min-w-max items-center gap-2 rounded-md px-3 py-1.5 text-xs font-medium transition-colors"
      :class="modelValue === item.id ? 'bg-background text-foreground shadow-sm' : 'text-muted-foreground hover:bg-background/60 hover:text-foreground'"
      :title="item.description"
      @click="emit('update:modelValue', item.id)"
    >
      <span>{{ item.label }}</span>
      <span v-if="item.badge !== undefined" class="rounded-full bg-muted px-1.5 py-0.5 text-[10px] tabular-nums text-muted-foreground">
        {{ item.badge }}
      </span>
    </button>
  </div>
</template>
