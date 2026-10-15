<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, type Component } from "vue"
import { useI18n } from "vue-i18n"
import { Activity, AppWindow, Bot, Blocks, Database, FileKey, FileText, FolderKanban, GitBranch, Globe, LayoutDashboard, Lock, Settings, ShieldCheck, TerminalSquare, Users, UsersRound, Wrench } from "lucide-vue-next"
import { platformNavigation, visiblePlatformPages } from "@/features/platform"
import type { PlatformPageId } from "@/features/platform/types"
import { projectContext } from "@/features/platform/model/project-context"
import { modules, parseModuleLocation, moduleLocationHash } from "@/features/modules"
import type { ModuleId } from "@/features/modules/types"
import {
  SidebarGroup, SidebarGroupContent, SidebarGroupLabel,
  SidebarMenu, SidebarMenuButton, SidebarMenuItem, SidebarMenuSub,
  SidebarMenuSubButton, SidebarMenuSubItem, useSidebar,
} from "@/shared/ui/sidebar"

const props=defineProps<{
  collapsed:boolean
  activePage:PlatformPageId
  publicCatalog?:boolean
  designPreview?:boolean
  presentationPages?: readonly PlatformPageId[]
}>()
const {t,locale}=useI18n()
const {isMobile,setOpenMobile}=useSidebar()
function closeMobileDrawer():void {
  if(isMobile.value)setOpenMobile(false)
}
const sections = computed(()=>[
  {key:"work",label:t("platform.navigation.work")},
  {key:"resources",label:t("platform.navigation.resources")},
  {key:"console",label:t("platform.navigation.console")},
] as const)
const items=computed(()=>{
  if(props.designPreview)return platformNavigation
  if(props.presentationPages)return platformNavigation.filter(item=>props.presentationPages!.includes(item.id))
  return props.publicCatalog?platformNavigation:visiblePlatformPages()
})
function allowed(id:PlatformPageId):boolean {
  if(props.designPreview)return true
  if(props.presentationPages)return props.presentationPages.includes(id)
  return !props.publicCatalog || id==="home"
}
const icons: Record<PlatformPageId, Component> = {
  home:LayoutDashboard,mcp:AppWindow,users:Users,teams:UsersRound,projects:FolderKanban,
  agents:Bot,sessions:ShieldCheck,integrations:GitBranch,variables:FileKey,
  dashboard:Activity,calls:Blocks,oauth:Wrench,files:FileText,terminal:TerminalSquare,
  "browser-managed":AppWindow,"browser-external":Globe,analysis:Database,settings:Settings,
}
const selectedModule=ref<ModuleId>("web")
function readSelection():void {
  selectedModule.value=parseModuleLocation(window.location.hash).module
}
function openModule(id:ModuleId):void {
  if(allowed("mcp")){
    window.location.hash=moduleLocationHash(id,"overview")
    closeMobileDrawer()
  }
}
onMounted(()=>{
  readSelection()
  window.addEventListener("hashchange",readSelection)
})
onBeforeUnmount(()=>window.removeEventListener("hashchange",readSelection))
function navigate(id:PlatformPageId){
  if(!allowed(id))return
  window.location.hash=`platform/${id}`
  closeMobileDrawer()
}
</script>
<template>
  <nav :aria-label="t('platform.navigation.title')" class="space-y-2">
    <SidebarGroup v-for="section in sections" :key="section.key" class="p-0">
      <SidebarGroupLabel>{{section.label}}</SidebarGroupLabel>
      <SidebarGroupContent>
        <SidebarMenu>
          <SidebarMenuItem v-for="item in items.filter(entry=>entry.section===section.key)" :key="item.id">
            <SidebarMenuButton :is-active="activePage===item.id" :tooltip="t(`platform.navigation.${item.title}`)"
              :disabled="!allowed(item.id)" :aria-disabled="!allowed(item.id)" @click="navigate(item.id)">
              <component :is="icons[item.id]" class="size-4" aria-hidden="true" />
              <span class="min-w-0 flex-1 truncate">{{t(`platform.navigation.${item.title}`)}}</span>
              <Lock v-if="!allowed(item.id)" class="size-3 shrink-0 opacity-70" aria-hidden="true" />
            </SidebarMenuButton>
            <!-- Historical nested Browser/Files/Git/Observability affordance,
                 implemented with shadcn-vue submenu and safe module deep links. -->
            <SidebarMenuSub v-if="item.id==='mcp' && activePage==='mcp' && allowed('mcp')" class="max-h-[42vh] overflow-y-auto">
              <SidebarMenuSubItem v-for="module in modules" :key="module.id">
                <SidebarMenuSubButton as="button" type="button" size="sm"
                  :is-active="selectedModule===module.id" @click="openModule(module.id)">
                  <span class="truncate">{{module.title[locale==='ru'?'ru':'en']}}</span>
                </SidebarMenuSubButton>
              </SidebarMenuSubItem>
            </SidebarMenuSub>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarGroupContent>
    </SidebarGroup>
  </nav>
</template>
