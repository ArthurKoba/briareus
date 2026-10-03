<script setup lang="ts">
import { computed } from "vue"
import { Activity, Circle, Radio, WifiOff } from "lucide-vue-next"
import { useI18n } from "vue-i18n"

import { eventBus } from "@/shared/events/bus"
import { formatDate } from "@/shared/lib/format"

const { t } = useI18n()
const live = computed(() => eventBus.state.status === "connected")
const connecting = computed(() => ["connecting", "reconnecting"].includes(eventBus.state.status))
const statusLabel = computed(() => live.value
  ? t("common.connected")
  : connecting.value
    ? t("realtime.connecting")
    : eventBus.state.enabled
      ? t("realtime.idle")
      : t("realtime.off"))
</script>

<template>
  <details class="group relative">
    <summary
      class="flex size-8 cursor-pointer list-none items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-accent hover:text-foreground [&::-webkit-details-marker]:hidden"
      :title="String(statusLabel)"
    >
      <Radio v-if="live" class="size-4 text-emerald-500" />
      <Activity v-else-if="connecting" class="size-4 animate-pulse text-amber-500" />
      <WifiOff v-else class="size-4" />
    </summary>

    <div class="absolute right-0 top-10 z-50 w-72 rounded-xl border border-border bg-popover p-3 text-popover-foreground shadow-xl">
      <div class="flex items-start justify-between gap-3">
        <div>
          <div class="text-sm font-semibold">{{ t("realtime.title") }}</div>
          <div class="mt-0.5 text-xs text-muted-foreground">{{ t("realtime.tabHint") }}</div>
        </div>
        <span class="inline-flex items-center gap-1 rounded-full bg-muted px-2 py-1 text-[10px] font-medium uppercase tracking-wide">
          <Circle class="size-2.5 fill-current" :class="live ? 'text-emerald-500' : connecting ? 'text-amber-500' : 'text-muted-foreground'" />
          {{ statusLabel }}
        </span>
      </div>

      <div class="mt-3 grid gap-2 rounded-lg bg-muted/50 p-2.5 text-xs">
        <div class="flex justify-between gap-4"><span class="text-muted-foreground">{{ t("realtime.subscriptions") }}</span><span class="font-mono">{{ eventBus.state.subscriptions }}</span></div>
        <div class="flex justify-between gap-4"><span class="text-muted-foreground">{{ t("realtime.transport") }}</span><span class="font-mono">{{ eventBus.state.transport }}</span></div>
        <div class="flex justify-between gap-4"><span class="text-muted-foreground">{{ t("realtime.lastEvent") }}</span><span class="text-right">{{ eventBus.state.enabled && eventBus.state.lastRemoteEventAt ? formatDate(eventBus.state.lastRemoteEventAt) : "—" }}</span></div>
      </div>

      <label class="mt-3 flex cursor-pointer items-center justify-between gap-3 rounded-lg border border-border/70 px-3 py-2.5">
        <span>
          <span class="block text-xs font-medium">{{ t("realtime.enabled") }}</span>
          <span class="mt-0.5 block text-[10px] text-muted-foreground">{{ t("realtime.enabledHint") }}</span>
        </span>
        <input
          type="checkbox"
          class="size-4 accent-current"
          :checked="eventBus.state.enabled"
          @change="eventBus.setEnabled(($event.target as HTMLInputElement).checked)"
        />
      </label>
    </div>
  </details>
</template>
