<script setup lang="ts">
import { AlertCircle, CheckCircle2, Info, TriangleAlert, X } from "lucide-vue-next"
import { notifications } from "./bus"
import { useI18n } from "vue-i18n"
const {t}=useI18n()
const icons={info:Info,success:CheckCircle2,warning:TriangleAlert,error:AlertCircle}
</script>
<template>
  <div class="pointer-events-none fixed right-4 top-4 z-[1000] flex w-[min(420px,calc(100vw-2rem))] flex-col gap-2">
    <transition-group name="toast">
      <article
        v-for="item in notifications.items.value"
        :key="item.id"
        class="pointer-events-auto rounded-xl border bg-card p-4 shadow-lg"
        :role="item.level==='error'?'alert':'status'"
        :class="item.level==='error'?'border-destructive/50':item.level==='warning'?'border-amber-500/40':'border-border'"
      >
        <div class="flex gap-3">
          <component :is="icons[item.level]" class="mt-0.5 size-4 shrink-0" aria-hidden="true" />
          <div class="min-w-0 flex-1">
            <div class="flex items-center gap-2 text-sm font-semibold">
              <span>{{ item.title }}</span>
              <span v-if="(item.count ?? 1) > 1" class="rounded-full bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">×{{ item.count }}</span>
            </div>
            <p v-if="item.description" class="mt-1 break-words text-xs text-muted-foreground">{{ item.description }}</p>
            <button v-if="item.action&&item.actionLabel" type="button" class="mt-2 text-xs font-medium underline focus-visible:outline-2 focus-visible:outline-offset-2" @click="item.action">{{item.actionLabel}}</button>
          </div>
          <button type="button" class="rounded p-1 hover:bg-accent focus-visible:outline-2 focus-visible:outline-offset-2" :aria-label="t('common.close')" @click="notifications.remove(item.id)"><X class="size-3.5" aria-hidden="true" /></button>
        </div>
      </article>
    </transition-group>
  </div>
</template>
