<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue"
import { useI18n } from "vue-i18n"

import AccountsPanel from "@/features/accounts/AccountsPanel.vue"
import SectionTabs from "@/shared/ui/SectionTabs.vue"

const { t } = useI18n()
const section = ref("github")
const items = computed(() => [
  { id: "github", label: "GitHub", description: t("git.githubHint") },
  { id: "gitlab", label: "GitLab", description: t("git.gitlabHint") },
])

function readHash(): void {
  const [, child] = location.hash.slice(1).split("/")
  if (child === "github" || child === "gitlab") section.value = child
}
function setSection(value: string): void {
  section.value = value
  history.replaceState(null, "", `#git/${value}`)
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
    <SectionTabs :model-value="section" :items="items" @update:model-value="setSection" />
    <AccountsPanel
      v-if="section === 'github'"
      title="GitHub"
      :description="t('git.githubHint')"
      :providers="['github']"
      default-provider="github"
    />
    <AccountsPanel
      v-else
      title="GitLab"
      :description="t('git.gitlabHint')"
      :providers="['gitlab']"
      default-provider="gitlab"
    />
  </div>
</template>
