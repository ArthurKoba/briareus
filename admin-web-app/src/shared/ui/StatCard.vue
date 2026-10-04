<script setup lang="ts">
interface Props {
  label: string
  value: string | number
  hint?: string
}

defineProps<Props>()
</script>

<template>
  <section class="rounded-xl border border-border bg-card p-4 shadow-sm">
    <div class="text-xs font-medium uppercase tracking-wide text-muted-foreground">{{ label }}</div>
    <div class="mt-2 text-2xl font-semibold tracking-tight">{{ value }}</div>
    <div v-if="hint" class="mt-1 text-xs text-muted-foreground">{{ hint }}</div>
    <div v-if="$slots.footer" class="mt-3 border-t border-border/50 pt-3"><slot name="footer" /></div>
  </section>
</template>
