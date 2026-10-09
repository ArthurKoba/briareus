<script setup lang="ts">
import { computed } from "vue"
import { useI18n } from "vue-i18n"
import { platformPort } from "@/features/platform/api/port"
import type { LoadStatus } from "@/features/platform/model/use-domain"
import type { UiError } from "@/features/platform/model/errors"
import { projectContext } from "@/features/platform/model/project-context"
import Button from "@/shared/ui/Button.vue"

const props = defineProps<{ status: LoadStatus; error?: UiError | null; actionError?: UiError | null; busy?: boolean; reconciled?: boolean }>()
const emit = defineEmits<{ retry: []; reconcile: [] }>()
const { t } = useI18n()
const blocked = computed(() => !platformPort.value ? "platform.pendingContract" : !projectContext.selection() ? "platform.chooseScope" : "platform.denied")
const errorText = computed(() => props.error ? t(`platform.errors.${props.error.message}`) : "")
</script>
<template>
  <div v-if="status === 'blocked'" class="rounded-lg border border-border bg-muted/35 p-4 text-sm text-muted-foreground" role="status">{{ t(blocked) }}</div>
  <div v-else-if="status === 'loading'" class="rounded-lg border border-border p-4 text-sm text-muted-foreground" role="status">{{ t('common.loading') }}</div>
  <div v-else-if="status === 'empty'" class="rounded-lg border border-border p-4 text-sm text-muted-foreground" role="status">{{ t('platform.empty') }}</div>
  <div v-else-if="status === 'error'" class="flex flex-wrap items-center gap-3 rounded-lg border border-destructive/30 p-4 text-sm text-destructive" role="alert">
    <span>{{ errorText }}</span><Button variant="outline" size="sm" @click="emit('retry')">{{ t('common.retry') }}</Button>
  </div>
  <p v-if="reconciled" role="status" class="rounded-md border border-border p-3 text-xs text-muted-foreground">{{t('platform.reconciledDoesNotProveCommit')}}</p>
  <div v-if="actionError" role="alert" class="flex flex-wrap items-center gap-3 rounded-md border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive">
    <span>{{t(`platform.errors.${actionError.message}`)}} <span v-if="actionError.kind === 'conflict'">{{t('platform.refreshBeforeRetry')}}</span></span>
    <Button v-if="['conflict','uncertain','unknown'].includes(actionError.kind)" size="sm" variant="outline" :disabled="busy" @click="emit('reconcile')">{{t('platform.reconcileBeforeRetry')}}</Button>
  </div>
</template>
