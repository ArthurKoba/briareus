<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue"
import { useI18n } from "vue-i18n"

import AccountsPanel from "@/features/accounts/AccountsPanel.vue"
import { VcsPolicyPanel } from "@/features/vcs-policy"
import SectionTabs from "@/shared/ui/SectionTabs.vue"

type Provider = "github" | "gitlab"
type Subsection = "accounts" | "parameters"

const { t } = useI18n()
const provider = ref<Provider>("github")
const subsection = ref<Subsection>("accounts")

const providerItems = computed(() => [
  { id: "github", label: "GitHub", description: t("git.githubHint") },
  { id: "gitlab", label: "GitLab", description: t("git.gitlabHint") },
])
const subsectionItems = computed(() => [
  { id: "accounts", label: t("git.accounts"), description: t("git.accountsHint", { provider: providerLabel.value }) },
  { id: "parameters", label: t("git.parameters"), description: t("git.parametersHint", { provider: providerLabel.value }) },
])
const providerLabel = computed(() => provider.value === "github" ? "GitHub" : "GitLab")

function syncHash(): void {
  history.replaceState(null, "", `#git/${provider.value}/${subsection.value}`)
}

function readHash(): void {
  const [, providerPart, subsectionPart] = location.hash.slice(1).split("/")
  if (providerPart === "github" || providerPart === "gitlab") provider.value = providerPart
  // Legacy #git/github and #git/gitlab links deliberately land on Accounts.
  subsection.value = subsectionPart === "parameters" ? "parameters" : "accounts"
}

function setProvider(value: string): void {
  if (value !== "github" && value !== "gitlab") return
  provider.value = value
  subsection.value = "accounts"
  syncHash()
}

function setSubsection(value: string): void {
  if (value !== "accounts" && value !== "parameters") return
  subsection.value = value
  syncHash()
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
      <h1 class="text-2xl font-semibold tracking-tight">{{ t("git.title") }}</h1>
      <p class="mt-1 text-sm text-muted-foreground">{{ t("git.description") }}</p>
    </div>

    <SectionTabs :model-value="provider" :items="providerItems" @update:model-value="setProvider" />

    <div class="rounded-xl border border-border/70 bg-card p-3">
      <SectionTabs :model-value="subsection" :items="subsectionItems" @update:model-value="setSubsection" />
    </div>

    <AccountsPanel
      v-if="subsection === 'accounts'"
      :title="providerLabel"
      :description="t('git.accountsHint', { provider: providerLabel })"
      :providers="[provider]"
      :default-provider="provider"
    />
    <VcsPolicyPanel v-else :provider="provider" />
  </div>
</template>
