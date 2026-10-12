<script setup lang="ts">
import { computed, type Component } from "vue"
import { useI18n } from "vue-i18n"
import { Activity, AppWindow, Bot, Blocks, Database, FileKey, FileText, FolderKanban, GitBranch, Globe, LayoutDashboard, Lock, Settings, ShieldCheck, TerminalSquare, Users, UsersRound, Wrench } from "lucide-vue-next"
import { visiblePlatformPages, type PlatformPageId } from "@/app/platform-navigation"
import { projectContext } from "@/features/platform/model/project-context"

const props=defineProps<{ collapsed:boolean; activePage:PlatformPageId }>()
const {t}=useI18n()
const sections = computed(()=>[
  {key:"work",label:t("platform.navigation.work")},
  {key:"resources",label:t("platform.navigation.resources")},
  {key:"console",label:t("platform.navigation.console")},
] as const)
const items=computed(()=>visiblePlatformPages())
const icons: Record<PlatformPageId, Component> = {
  home:LayoutDashboard,users:Users,teams:UsersRound,projects:FolderKanban,
  agents:Bot,sessions:ShieldCheck,integrations:GitBranch,variables:FileKey,
  dashboard:Activity,calls:Blocks,oauth:Wrench,files:FileText,terminal:TerminalSquare,
  "browser-managed":AppWindow,"browser-external":Globe,analysis:Database,settings:Settings,
}
function navigate(id:PlatformPageId){ window.location.hash=`platform/${id}` }
</script>
<template>
  <nav :aria-label="t('platform.navigation.title')" class="space-y-4">
    <div v-for="section in sections" :key="section.key" class="space-y-1">
      <div v-if="!collapsed" class="px-3 pb-1 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">{{section.label}}</div>
      <button v-for="item in items.filter(item=>item.section===section.key)" :key="item.id" type="button" class="flex w-full items-center gap-2 rounded-md px-3 py-2 text-left text-xs transition-colors" :class="activePage===item.id?'bg-accent font-semibold text-foreground':'text-muted-foreground hover:bg-accent hover:text-foreground'" :aria-current="activePage===item.id?'page':undefined" :title="collapsed?t(`platform.navigation.${item.title}`):undefined" @click="navigate(item.id)">
        <component :is="icons[item.id]" class="size-4 shrink-0" aria-hidden="true" /><span v-if="!collapsed" class="min-w-0 flex-1 truncate">{{t(`platform.navigation.${item.title}`)}}</span><Lock v-if="!collapsed && ((item.scope==='project' && item.permissions.length>0 && !item.permissions.some(permission=>projectContext.can(permission))))" class="size-3 shrink-0 opacity-50" :aria-label="t('platform.resourceBlocked')" />
      </button>
    </div>
    <p v-if="!collapsed && projectContext.state.scope==='choose-project'" class="px-3 text-xs text-muted-foreground">{{t('platform.chooseScope')}}</p>
  </nav>
</template>
