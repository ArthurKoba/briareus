<script setup lang="ts">
import { computed, ref, watch } from "vue"
import { useI18n } from "vue-i18n"
import Button from "@/shared/ui/Button.vue"
import AppDialog from "@/shared/ui/AppDialog.vue"

const props = defineProps<{ open: boolean; title: string; detail: string; target: string; busy?: boolean }>()
const emit = defineEmits<{ cancel: []; confirm: [] }>()
const typed = ref("")
const { t } = useI18n()
watch(() => props.open, () => { typed.value = "" })
const allowed = computed(() => props.target.trim().length > 0 && typed.value === props.target && !props.busy)
</script>
<template>
  <AppDialog :open="open" :title="title" width="520px" @close="!busy && emit('cancel')">
    <p class="mb-4 text-sm text-muted-foreground">{{detail}}</p>
    <label class="block text-sm">
      <span>{{t('platform.typeToConfirm', { target })}}</span>
      <input v-model="typed" class="field mt-2" autofocus autocomplete="off" :disabled="busy" @keyup.enter="allowed && emit('confirm')" />
    </label>
    <template #footer>
      <Button variant="outline" :disabled="busy" @click="emit('cancel')">{{t('common.cancel')}}</Button>
      <Button variant="destructive" :disabled="!allowed" @click="emit('confirm')">{{t('common.confirm')}}</Button>
    </template>
  </AppDialog>
</template>
