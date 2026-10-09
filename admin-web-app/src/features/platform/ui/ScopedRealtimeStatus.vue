<script setup lang="ts">
import { computed } from "vue"
import { Wifi, WifiOff, RefreshCcw } from "lucide-vue-next"
import { useI18n } from "vue-i18n"
import { scopedEvents } from "@/features/platform/model/project-events"
import { platformPort } from "@/features/platform/api/port"
import Button from "@/shared/ui/Button.vue"

const { t } = useI18n()
const status = computed(() => scopedEvents.state.status)
const canReconnect = computed(() => platformPort.value?.capabilities?.scopedRealtime === true &&
  ["reconnecting", "error", "idle"].includes(status.value))
const title = computed(() => `${t('platform.realtimeStatus')}: ${t(`platform.scopedRealtime.${status.value}`)}`)
</script>
<template>
  <div class="hidden min-w-0 items-center gap-1.5 md:flex" role="status" :aria-label="title" :title="title">
    <Wifi v-if="status==='connected'" class="size-4 text-emerald-600 dark:text-emerald-400" aria-hidden="true" />
    <WifiOff v-else class="size-4 text-muted-foreground" aria-hidden="true" />
    <span class="hidden max-w-24 truncate text-xs text-muted-foreground xl:inline">{{t(`platform.scopedRealtime.${status}`)}}</span>
    <Button v-if="canReconnect" variant="ghost" size="icon" :aria-label="t('platform.retryRealtime')" @click="scopedEvents.reconnect()"><RefreshCcw class="size-3.5" aria-hidden="true" /></Button>
  </div>
</template>
