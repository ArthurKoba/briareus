<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue"

import { uiPreferences } from "@/shared/lib/preferences"

const props = withDefaults(defineProps<{ value: string | Date; intervalMs?: number }>(), { intervalMs: 2000 })
const now = ref(Date.now())
let timer = 0

const timestamp = computed(() => props.value instanceof Date ? props.value.getTime() : new Date(props.value).getTime())
const formatter = computed(() => new Intl.RelativeTimeFormat(uiPreferences.locale.value === "ru" ? "ru-RU" : "en-US", { numeric: "auto" }))
const label = computed(() => {
  const seconds = Math.round((timestamp.value - now.value) / 1000)
  const absolute = Math.abs(seconds)
  if (absolute < 60) return formatter.value.format(seconds, "second")
  const minutes = Math.round(seconds / 60)
  if (Math.abs(minutes) < 60) return formatter.value.format(minutes, "minute")
  const hours = Math.round(minutes / 60)
  if (Math.abs(hours) < 24) return formatter.value.format(hours, "hour")
  return formatter.value.format(Math.round(hours / 24), "day")
})

onMounted(() => { timer = window.setInterval(() => { now.value = Date.now() }, Math.max(1000, props.intervalMs)) })
onBeforeUnmount(() => window.clearInterval(timer))
</script>

<template><span :title="new Date(timestamp).toLocaleString()">{{ label }}</span></template>
