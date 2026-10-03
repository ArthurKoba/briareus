<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue"
import {
  Activity,
  AppWindow,
  Blocks,
  Bot,
  ChartNoAxesCombined,
  ChevronDown,
  Database,
  FileText,
  GitBranch,
  Settings,
  TerminalSquare,
} from "lucide-vue-next"
import { useI18n } from "vue-i18n"

const props = defineProps<{ collapsed: boolean; activePage: string }>()
const { t } = useI18n()
const routePath = ref(location.hash.slice(1) || "dashboard")

const items = computed(() => [
  { id: "dashboard", label: t("nav.dashboard"), icon: Activity },
  { id: "git", label: t("nav.git"), icon: GitBranch, children: [
    { path: "git/github", label: "GitHub" }, { path: "git/gitlab", label: "GitLab" },
  ] },
  { id: "observability", label: t("nav.observability"), icon: ChartNoAxesCombined, children: [
    { path: "observability/signoz", label: "SigNoz" },
    { path: "observability/coolify", label: "Coolify" },
    { path: "observability/telemetry", label: t("telemetry.title") },
  ] },
  { id: "calls", label: t("nav.calls"), icon: Blocks },
  { id: "files", label: t("nav.files"), icon: FileText },
  { id: "terminal", label: t("nav.terminal"), icon: TerminalSquare },
  { id: "browser", label: t("nav.browser"), icon: AppWindow },
  { id: "analysis", label: t("nav.analysis"), icon: Database },
  { id: "oauth", label: t("nav.oauth"), icon: Bot },
  { id: "settings", label: t("nav.settings"), icon: Settings, children: [
    { path: "settings/interface", label: t("settings.interface") },
    { path: "settings/realtime", label: t("settings.realtime") },
    { path: "settings/logging", label: t("settings.logging") },
    { path: "settings/mcp", label: t("settings.mcp") },
  ] },
])

function sync(): void { routePath.value = location.hash.slice(1) || "dashboard" }
function navigate(path: string): void { location.hash = path }
function selectRoot(item: (typeof items.value)[number]): void { navigate(item.children?.[0]?.path ?? item.id) }

onMounted(() => window.addEventListener("hashchange", sync))
onBeforeUnmount(() => window.removeEventListener("hashchange", sync))
</script>

<template>
  <nav class="space-y-1">
    <div v-for="item in items" :key="item.id">
      <button
        class="flex h-9 w-full items-center gap-3 rounded-md px-3 text-sm transition"
        :class="activePage === item.id ? 'bg-accent text-foreground' : 'text-muted-foreground hover:bg-accent hover:text-foreground'"
        :title="collapsed ? String(item.label) : undefined"
        @click="selectRoot(item)"
      >
        <component :is="item.icon" class="size-4 shrink-0" />
        <span v-if="!collapsed" class="min-w-0 flex-1 truncate text-left">{{ item.label }}</span>
        <ChevronDown v-if="!collapsed && item.children?.length" class="size-3.5 shrink-0" :class="activePage === item.id && 'rotate-180'" />
      </button>
      <div v-if="!collapsed && activePage === item.id && item.children?.length" class="ml-5 mt-1 space-y-0.5 border-l border-border pl-2">
        <button
          v-for="child in item.children"
          :key="child.path"
          class="block w-full rounded-md px-3 py-1.5 text-left text-xs transition"
          :class="routePath === child.path ? 'bg-background font-medium text-foreground shadow-sm' : 'text-muted-foreground hover:bg-accent hover:text-foreground'"
          @click="navigate(child.path)"
        >{{ child.label }}</button>
      </div>
    </div>
  </nav>
</template>
