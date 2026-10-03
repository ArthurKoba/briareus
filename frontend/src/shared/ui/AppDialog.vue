<script setup lang="ts">
import { Teleport } from "vue"
import { X } from "lucide-vue-next"

withDefaults(defineProps<{
  open: boolean
  title: string
  width?: string
  closeLabel?: string
}>(), {
  width: "760px",
  closeLabel: "Close",
})

const emit = defineEmits<{ close: [] }>()
</script>

<template>
  <Teleport to="body">
    <div v-if="open" class="fixed inset-0 z-[900] grid place-items-center p-4">
      <button class="absolute inset-0 bg-black/60 backdrop-blur-[1px]" :aria-label="closeLabel" @click="emit('close')" />
      <section
        class="relative z-10 max-h-[90vh] w-full overflow-hidden rounded-2xl border border-border bg-card text-foreground shadow-2xl"
        :style="{ maxWidth: width }"
        role="dialog"
        aria-modal="true"
      >
        <header class="flex items-center justify-between border-b border-border px-5 py-4">
          <h2 class="text-base font-semibold tracking-tight">{{ title }}</h2>
          <button class="rounded-md p-1.5 text-muted-foreground hover:bg-accent hover:text-foreground" @click="emit('close')">
            <X class="size-4" />
          </button>
        </header>
        <div class="max-h-[calc(90vh-68px)] overflow-auto p-5">
          <slot />
        </div>
        <footer v-if="$slots.footer" class="flex items-center justify-end gap-2 border-t border-border px-5 py-3">
          <slot name="footer" />
        </footer>
      </section>
    </div>
  </Teleport>
</template>
