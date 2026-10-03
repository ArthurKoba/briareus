<script setup lang="ts">
import { computed } from "vue"

const props = defineProps<{ value: string | unknown }>()

const formatted = computed(() => {
  if (typeof props.value !== "string") return JSON.stringify(props.value, null, 2)
  const raw = props.value.trim()
  if (!raw) return ""
  try {
    return JSON.stringify(JSON.parse(raw), null, 2)
  } catch {
    return raw
  }
})
</script>

<template>
  <pre class="max-h-80 overflow-auto rounded-lg border border-border/60 bg-muted/60 p-3 font-mono text-xs leading-5 whitespace-pre-wrap break-words">{{ formatted || "—" }}</pre>
</template>
