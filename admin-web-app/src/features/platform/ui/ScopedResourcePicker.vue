<script setup lang="ts">
import { computed, ref, watch } from "vue"
import { useI18n } from "vue-i18n"
import type { ResourceOwner } from "@/features/platform/model/contracts"
import Button from "@/shared/ui/Button.vue"

export interface ScopedResourceChoice { id: string; name: string; owner: ResourceOwner }
const props = defineProps<{ items: readonly ScopedResourceChoice[]; label: string }>()
const emit = defineEmits<{ choose: [selection: ScopedResourceChoice | null] }>()
const { t } = useI18n()
const selectedKey = ref("")
function identity(item: ScopedResourceChoice): string {
  return `${item.owner.kind}:${item.owner.kind === "team" ? item.owner.teamId : item.owner.projectId}:${item.id}`
}
const counts = computed(() => {
  const map = new Map<string, number>()
  for (const item of props.items) map.set(item.name, (map.get(item.name) ?? 0) + 1)
  return map
})
const duplicates = computed(() => [...counts.value.values()].some(count => count > 1))
const selected = computed(() => props.items.find(item => identity(item) === selectedKey.value) ?? null)
watch(() => props.items, () => {
  if (selectedKey.value && !selected.value) selectedKey.value = ""
})
watch(selected, choice => { emit("choose", choice ? { ...choice } : null) })
function ownerId(item: ScopedResourceChoice): string {
  return item.owner.kind === "team" ? item.owner.teamId : item.owner.projectId
}
async function copyId(): Promise<void> {
  if (!selected.value) return
  try { await navigator.clipboard.writeText(selected.value.id) } catch { /* ID also selectable in the text input */ }
}
</script>

<template>
  <div v-if="items.length" class="space-y-3 rounded-lg border border-border bg-muted/20 p-4">
    <p v-if="duplicates" role="status" class="text-xs font-medium text-foreground">{{ t('platform.resourceAliasCollision') }}</p>
    <label class="block max-w-xl text-xs">
      {{ label }}
      <select v-model="selectedKey" class="field mt-1" :aria-label="label">
        <option value="">{{ t('platform.selectExactResource') }}</option>
        <option v-for="item in items" :key="identity(item)" :value="identity(item)">
          {{ item.name }} · {{ item.owner.kind === 'team' ? t('platform.teamOwned') : t('platform.projectOwned') }} · {{ item.id.slice(0, 12) }}
        </option>
      </select>
    </label>
    <div v-if="selected" class="flex flex-wrap items-end gap-3">
      <label class="min-w-0 flex-1 text-xs">
        {{ t('platform.resourceId') }}
        <input class="field mt-1 font-mono text-xs" readonly :value="selected.id" @focus="($event.target as HTMLInputElement).select()" />
      </label>
      <label class="min-w-0 flex-1 text-xs">
        {{ t('platform.sourceOwner') }}
        <input class="field mt-1 font-mono text-xs" readonly :value="`${selected.owner.kind}:${ownerId(selected)}`" @focus="($event.target as HTMLInputElement).select()" />
      </label>
      <Button variant="outline" size="sm" @click="copyId">{{ t('platform.copyId') }}</Button>
    </div>
    <p class="text-xs text-muted-foreground">{{ t('platform.qualifiedSelectionHint') }}</p>
  </div>
</template>
