<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue"
import { useI18n } from "vue-i18n"

import AccountsPanel from "@/features/accounts/AccountsPanel.vue"
import TelemetryPanel from "@/features/telemetry/TelemetryPanel.vue"
import SectionTabs from "@/shared/ui/SectionTabs.vue"

const { t } = useI18n()
const section = ref("signoz")
const items = computed(() => [
  { id: "signoz", label: "SigNoz", description: t("observability.signozHint") },
  { id: "coolify", label: "Coolify", description: t("observability.coolifyHint") },
  { id: "telemetry", label: t("telemetry.title"), description: t("observability.telemetryHint") },
])

function readHash(): void {
  const [, child] = location.hash.slice(1).split("/")
  if (["signoz", "coolify", "telemetry"].includes(child ?? "")) section.value = child!
}
function setSection(value: string): void {
  section.value = value
  history.replaceState(null, "", `#observability/${value}`)
}

onMounted(() => {
  readHash()
  window.addEventListener("hashchange", readHash)
})
onBeforeUnmount(() => window.removeEventListener("hashchange", readHash))
</script>

<template>
  <div class="space-y-5">
    <div>
      <h1 class="text-2xl font-semibold tracking-tight">{{ t("observability.title") }}</h1>
      <p class="mt-1 text-sm text-muted-foreground">{{ t("observability.description") }}</p>
    </div>
    <SectionTabs :model-value="section" :items="items" @update:model-value="setSection" />
    <AccountsPanel
      v-if="section === 'signoz'"
      title="SigNoz"
      :description="t('observability.signozHint')"
      :providers="['signoz']"
      default-provider="signoz"
    />
    <AccountsPanel
      v-else-if="section === 'coolify'"
      title="Coolify"
      :description="t('observability.coolifyHint')"
      :providers="['coolify']"
      default-provider="coolify"
    />
    <TelemetryPanel v-else />
  </div>
</template>
