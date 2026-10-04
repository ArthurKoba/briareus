<script setup lang="ts">
import { computed } from "vue"
import { Activity, Circle, Wifi, WifiOff } from "lucide-vue-next"
import { PopoverContent, PopoverPortal, PopoverRoot, PopoverTrigger } from "reka-ui"
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

function toggle(): void {
  eventBus.setEnabled(!eventBus.state.enabled)
}
</script>

<template>
  <PopoverRoot>
    <PopoverTrigger as-child>
      <button
        type="button"
        class="grid size-8 place-items-center rounded-md text-muted-foreground transition-colors hover:bg-accent hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        :title="String(`${t('realtime.title')}: ${statusLabel}`)"
        :aria-label="String(`${t('realtime.title')}: ${statusLabel}`)"
      >
        <Wifi v-if="live" class="size-4 text-emerald-500" />
        <Activity v-else-if="connecting" class="size-4 animate-pulse text-amber-500" />
        <WifiOff v-else class="size-4" />
      </button>
    </PopoverTrigger>
    <PopoverPortal>
      <PopoverContent
        align="end"
        side="bottom"
        :side-offset="8"
        class="z-50 w-72 rounded-xl border border-border bg-popover p-3 text-popover-foreground shadow-xl outline-none"
      >
        <div class="flex items-start justify-between gap-3">
          <div class="min-w-0">
            <div class="text-sm font-semibold">{{ t("realtime.title") }}</div>
            <div class="mt-0.5 text-xs text-muted-foreground">{{ t("realtime.tabHint") }}</div>
          </div>
          <span class="inline-flex shrink-0 items-center gap-1 rounded-full bg-muted px-2 py-1 text-[10px] font-medium uppercase tracking-wide">
            <Circle class="size-2.5 fill-current" :class="live ? 'text-emerald-500' : connecting ? 'text-amber-500' : eventBus.state.enabled ? 'text-muted-foreground' : 'text-red-500'" />
            {{ statusLabel }}
          </span>
        </div>

        <div class="mt-3 flex items-center justify-between gap-3 rounded-lg border border-border/70 px-3 py-2.5">
          <div>
            <div class="text-xs font-medium">{{ t("realtime.enabled") }}</div>
            <div class="mt-0.5 text-[10px] text-muted-foreground">{{ t("realtime.enabledHint") }}</div>
          </div>
          <button
            type="button"
            role="switch"
            :aria-checked="eventBus.state.enabled"
            :aria-label="String(eventBus.state.enabled ? t('realtime.turnOff') : t('realtime.turnOn'))"
            class="relative h-6 w-11 shrink-0 rounded-full transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
            :class="eventBus.state.enabled ? 'bg-emerald-500' : 'bg-red-500'"
            @click="toggle"
          >
            <span
              class="absolute top-0.5 size-5 rounded-full bg-white shadow-sm transition-transform"
              :class="eventBus.state.enabled ? 'translate-x-5' : 'translate-x-0.5'"
            />
          </button>
        </div>

        <div class="mt-2 flex items-center justify-between rounded-lg bg-muted/50 px-3 py-2 text-xs">
          <span class="text-muted-foreground">{{ t("realtime.lastEvent") }}</span>
          <span class="text-right">{{ eventBus.state.enabled && eventBus.state.lastRemoteEventAt ? formatDate(eventBus.state.lastRemoteEventAt) : "—" }}</span>
        </div>
      </PopoverContent>
    </PopoverPortal>
  </PopoverRoot>
</template>
