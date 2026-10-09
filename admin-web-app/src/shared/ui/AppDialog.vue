<script setup lang="ts">
import { nextTick, onBeforeUnmount, ref, useId, watch } from "vue"
import { Teleport } from "vue"
import { X } from "lucide-vue-next"

const props = withDefaults(defineProps<{
  open: boolean
  title: string
  width?: string
  closeLabel?: string
}>(), {
  width: "760px",
  closeLabel: "Close",
})
const emit = defineEmits<{ close: [] }>()
const panel = ref<HTMLElement | null>(null)
const titleId = useId()
let focusBeforeDialog: HTMLElement | null = null

function restoreFocus(): void {
  if (focusBeforeDialog?.isConnected) focusBeforeDialog.focus()
  focusBeforeDialog = null
}
watch(() => props.open, async (open) => {
  if (!open) { restoreFocus(); return }
  focusBeforeDialog = document.activeElement instanceof HTMLElement ? document.activeElement : null
  await nextTick()
  if (!props.open) return
  const first = panel.value?.querySelector<HTMLElement>("[autofocus], input:not(:disabled), select:not(:disabled), textarea:not(:disabled), button:not(:disabled)")
  ;(first ?? panel.value)?.focus()
}, { flush: "post" })
onBeforeUnmount(restoreFocus)

function handleKeydown(event: KeyboardEvent): void {
  if (event.key === "Escape") { event.stopPropagation(); emit("close"); return }
  if (event.key !== "Tab" || !panel.value) return
  const candidates = [...panel.value.querySelectorAll<HTMLElement>("button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), a[href], [tabindex]:not([tabindex='-1'])")]
  const focusable = candidates.filter(item => item.getClientRects().length > 0 && !item.closest("[inert]"))
  const first = focusable[0]
  const last = focusable[focusable.length - 1]
  if (!first || !last) { event.preventDefault(); panel.value.focus(); return }
  if (event.shiftKey && (document.activeElement === first || !panel.value.contains(document.activeElement))) { event.preventDefault(); last.focus() }
  else if (!event.shiftKey && (document.activeElement === last || !panel.value.contains(document.activeElement))) { event.preventDefault(); first.focus() }
}
</script>

<template>
  <Teleport to="body">
    <div v-if="open" class="fixed inset-0 z-[900] grid place-items-center p-4">
      <button type="button" class="absolute inset-0 bg-black/60 backdrop-blur-[1px]" :aria-label="closeLabel" tabindex="-1" @click="emit('close')" />
      <section
        ref="panel"
        class="relative z-10 max-h-[90vh] w-full overflow-hidden rounded-2xl border border-border bg-card text-foreground shadow-2xl"
        :style="{ maxWidth: width }"
        role="dialog"
        aria-modal="true"
        :aria-labelledby="titleId"
        tabindex="-1"
        @keydown="handleKeydown"
      >
        <header class="flex items-center justify-between border-b border-border px-5 py-4">
          <h2 :id="titleId" class="text-base font-semibold tracking-tight">{{ title }}</h2>
          <button type="button" class="rounded-md p-1.5 text-muted-foreground hover:bg-accent hover:text-foreground" :aria-label="closeLabel" @click="emit('close')">
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
