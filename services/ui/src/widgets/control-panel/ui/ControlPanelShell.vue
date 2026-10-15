<script setup lang="ts">
import { computed } from "vue"
import { useI18n } from "vue-i18n"
import { LockKeyhole, Moon, Palette, Sun } from "lucide-vue-next"
import type { PlatformPageId } from "@/features/platform/types"
import PlatformNav from "./PlatformNav.vue"
import { useUiPreferences } from "@/shared/lib/preferences"
import { Button } from "@/shared/ui/button"
import {
  Sidebar, SidebarContent, SidebarFooter, SidebarHeader, SidebarInset,
  SidebarProvider, SidebarTrigger,
} from "@/shared/ui/sidebar"
import { Separator } from "@/shared/ui/separator"
import { Popover, PopoverTrigger, PopoverContent } from "@/shared/ui/popover"

const props = defineProps<{
  page: PlatformPageId
  heading: string
  authenticated: boolean
  busy?: boolean
  designPreview?: boolean
  presentationOnly?: boolean
  presentationPages?: readonly PlatformPageId[]
}>()
const emit = defineEmits<{ logout: [] }>()
const { t, locale } = useI18n()
const preferences = useUiPreferences()
const sidebarOpen = computed({
  get: () => !preferences.sidebarCollapsed.value,
  set: value => { preferences.sidebarCollapsed.value = !value },
})
const status = computed(() => locale.value === "ru"
  ? props.designPreview ? "Локальный дизайн-просмотр · без серверных прав"
    : props.presentationOnly ? "Пользователь подтверждён · права проверяются сервером"
    : props.authenticated ? "Подтверждённый доступ" : "Требуется вход"
  : props.designPreview ? "Local design preview · no server permissions"
    : props.presentationOnly ? "Identity verified · server controls permissions"
    : props.authenticated ? "Verified access" : "Sign-in required")
</script>

<template>
  <SidebarProvider v-model:open="sidebarOpen" class="bg-background text-foreground">
    <Sidebar collapsible="icon" variant="sidebar">
      <SidebarHeader class="min-h-16 border-b border-sidebar-border p-3">
        <div class="flex min-w-0 items-center gap-2 px-1">
          <span class="grid size-9 shrink-0 place-items-center rounded-lg bg-primary text-sm font-black text-primary-foreground" aria-hidden="true">B</span>
          <div class="min-w-0 group-data-[collapsible=icon]:hidden">
            <p class="truncate text-sm font-semibold tracking-tight">BRIAREUS</p>
            <p class="truncate text-[11px] text-muted-foreground">Control Panel</p>
          </div>
        </div>
      </SidebarHeader>
      <SidebarContent class="p-2">
        <PlatformNav :active-page="page" :collapsed="!sidebarOpen" :public-catalog="!authenticated" :design-preview="designPreview" :presentation-pages="presentationPages" />
      </SidebarContent>
      <SidebarFooter class="border-t border-sidebar-border p-3">
        <div class="flex items-start gap-2 text-xs text-muted-foreground group-data-[collapsible=icon]:hidden">
          <LockKeyhole class="mt-0.5 size-4 shrink-0" aria-hidden="true" />
          <p>{{ status }}</p>
        </div>
      </SidebarFooter>
    </Sidebar>

    <SidebarInset class="min-w-0">
      <header class="sticky top-0 z-20 flex h-16 shrink-0 items-center gap-3 border-b border-border bg-background/95 px-4 backdrop-blur sm:px-6">
        <SidebarTrigger class="shrink-0" :aria-label="locale==='ru'?'Развернуть или скрыть меню':'Toggle sidebar'" />
        <Separator orientation="vertical" class="h-5" />
        <h1 id="briareus-page-title" tabindex="-1" class="min-w-0 flex-1 truncate text-sm font-semibold tracking-tight outline-none focus-visible:ring-2 focus-visible:ring-ring">{{ heading }}</h1>
        <div class="flex shrink-0 items-center gap-1.5 sm:gap-2">
          <Popover>
            <PopoverTrigger as-child>
              <Button variant="ghost" size="icon" :aria-label="locale==='ru'?'Настройки цветов':'Accent settings'"><Palette class="size-4"/></Button>
            </PopoverTrigger>
            <PopoverContent align="end" class="w-60 space-y-3">
              <p class="text-sm font-semibold">{{locale==='ru'?'Цветовая палитра':'Color palette'}}</p>
              <div class="flex flex-wrap gap-2">
                <Button v-for="accent in (['graphite','indigo','amber'] as const)" :key="accent" size="sm"
                  :variant="preferences.accent.value===accent?'default':'outline'" :aria-pressed="preferences.accent.value===accent"
                  @click="preferences.accent.value=accent">
                  {{accent==='graphite'?(locale==='ru'?'Графит':'Graphite'):accent==='indigo'?(locale==='ru'?'Индиго':'Indigo'):(locale==='ru'?'Янтарь':'Amber')}}
                </Button>
              </div>
            </PopoverContent>
          </Popover>
          <Button variant="ghost" size="icon" :aria-label="t('settings.theme')" @click="preferences.theme.value=preferences.theme.value==='dark'?'light':'dark'">
            <Sun v-if="preferences.theme.value==='dark'" class="size-4" /><Moon v-else class="size-4" />
          </Button>
          <Button v-if="authenticated" variant="outline" size="sm" :disabled="busy" @click="emit('logout')">{{ t('app.signOut') }}</Button>
        </div>
      </header>
      <div class="min-w-0 flex-1 p-4 sm:p-6">
        <div class="mx-auto w-full max-w-[1560px]">
          <slot />
        </div>
      </div>
    </SidebarInset>
  </SidebarProvider>
</template>
