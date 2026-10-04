<script setup lang="ts">
import { RefreshCw } from "lucide-vue-next"
import { useI18n } from "vue-i18n"

import Button from "@/shared/ui/Button.vue"

withDefaults(defineProps<{ synced: boolean; loading?: boolean }>(), { loading: false })
const emit = defineEmits<{ refresh: [] }>()
const { t } = useI18n()
</script>

<template>
  <Button v-if="!synced" variant="outline" size="sm" :disabled="loading" @click="emit('refresh')">
    <RefreshCw class="mr-2 size-4" />{{ t("common.refresh") }}
  </Button>
</template>
