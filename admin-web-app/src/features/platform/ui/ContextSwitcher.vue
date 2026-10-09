<script setup lang="ts">
import { computed } from "vue"
import { FolderKanban, LockKeyhole } from "lucide-vue-next"
import { useI18n } from "vue-i18n"

import { projectContext } from "@/features/platform/model/project-context"

const { t } = useI18n()
// Equal display names across Team/Project owners are not unique identities.
const shortId=(value:string):string=>value.slice(0,8)
const personal = computed(() => projectContext.state.projects.filter(project => project.ownership === "personal"))
const teams = computed(() => projectContext.state.projects.filter(project => project.ownership === "team"))
const teamScopes = computed(() => projectContext.state.teams)
const selection = computed(() => {
  if (projectContext.state.scope === "operator") return "operator"
  if (projectContext.state.scope === "team") return `team:${projectContext.state.activeTeamKey}`
  if (projectContext.state.scope === "project") return `project:${projectContext.state.activeProjectKey}`
  return "account"
})

function choose(event: Event): void {
  const value = (event.target as HTMLSelectElement).value
  if (value === "account") projectContext.selectNone()
  else if (value === "operator") projectContext.selectOperator()
  else if (value.startsWith("project:")) projectContext.selectProject(value.slice(8))
  else if (value.startsWith("team:")) projectContext.selectTeam(value.slice(5))
}
</script>

<template>
  <div class="flex min-w-0 items-center gap-2 text-xs">
    <FolderKanban class="size-4 shrink-0 text-muted-foreground" aria-hidden="true" />
    <label v-if="projectContext.state.user" class="min-w-0">
      <span class="sr-only">{{ t('context.selector') }}</span>
      <select class="field max-w-36 py-1 text-xs sm:max-w-48 xl:max-w-64" :value="selection" :aria-label="t('context.selector')" @change="choose">
        <option value="account">{{ t('context.accountContext') }}</option>
        <optgroup v-if="personal.length" :label="t('context.personal')">
          <option v-for="project in personal" :key="project.key" :value="`project:${project.key}`">{{ project.label }} · {{ shortId(project.key) }}</option>
        </optgroup>
        <optgroup v-if="teams.length" :label="t('context.teams')">
          <option v-for="project in teams" :key="project.key" :value="`project:${project.key}`">{{ project.label }}{{ project.ownerLabel ? ` · ${project.ownerLabel}` : '' }} · {{shortId(project.key)}}</option>
        </optgroup>
        <optgroup v-if="teamScopes.length" :label="t('context.teamResources')">
          <option v-for="team in teamScopes" :key="team.key" :value="`team:${team.key}`">{{ team.label }} · {{shortId(team.key)}}</option>
        </optgroup>
        <option v-if="projectContext.state.user.isSuperuser" value="operator">{{ t('context.operator') }}</option>
      </select>
    </label>
    <span v-else class="inline-flex items-center gap-1.5 text-muted-foreground" :title="t('context.contractPending')">
      <LockKeyhole class="size-3.5 shrink-0" aria-hidden="true" />
      <span class="hidden lg:inline">{{ t('context.legacy') }}</span>
      <span class="hidden 2xl:inline">· {{ t('context.contractPending') }}</span>
    </span>
  </div>
</template>
