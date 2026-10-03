<script setup lang="ts">
import { onMounted, ref } from "vue"
import { Activity, AppWindow, Blocks, Bot, Database, FileText, Github, Moon, PanelLeftClose, PanelLeftOpen, Settings, Sun, TerminalSquare } from "lucide-vue-next"

import { managementApi, type ManagementBootstrap, type SessionState } from "@/shared/api/management"
import { useUiPreferences } from "@/shared/lib/preferences"
import Button from "@/shared/ui/Button.vue"

const session = ref<SessionState | null>(null)
const bootstrap = ref<ManagementBootstrap | null>(null)
const loading = ref(true)
const error = ref("")
const username = ref("")
const password = ref("")
const { theme, sidebarCollapsed } = useUiPreferences()

const items = [
  ["Overview", Activity], ["Accounts", Github], ["MCP Calls", Blocks], ["Files", FileText],
  ["Terminal", TerminalSquare], ["Browser", AppWindow], ["Analysis", Database],
  ["OAuth", Bot], ["Settings", Settings],
] as const

async function load(): Promise<void> {
  loading.value = true
  try {
    session.value = await managementApi.session()
    bootstrap.value = session.value.authenticated ? await managementApi.bootstrap() : null
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : "Unable to load management console"
  } finally {
    loading.value = false
  }
}

async function login(): Promise<void> {
  error.value = ""
  try {
    session.value = await managementApi.login(username.value, password.value)
    password.value = ""
    bootstrap.value = await managementApi.bootstrap()
  } catch {
    error.value = "Invalid username or password"
  }
}

async function logout(): Promise<void> {
  session.value = await managementApi.logout()
  bootstrap.value = null
}

function toggleTheme(): void {
  theme.value = theme.value === "dark" ? "light" : "dark"
}

onMounted(load)
</script>

<template>
  <div v-if="loading" class="grid min-h-screen place-items-center bg-background text-sm text-muted-foreground">
    Loading management…
  </div>

  <div v-else-if="!session?.authenticated" class="grid min-h-screen place-items-center bg-muted/30 p-6">
    <section class="w-full max-w-sm rounded-xl border border-border bg-card p-6 shadow-sm">
      <h1 class="text-xl font-semibold">MCP Management</h1>
      <p class="mt-1 text-sm text-muted-foreground">Sign in to the management console.</p>
      <form class="mt-6 space-y-4" @submit.prevent="login">
        <label class="block space-y-1.5 text-sm">
          <span>Username</span>
          <input v-model="username" autocomplete="username" class="h-9 w-full rounded-md border border-input bg-background px-3 outline-none focus:ring-2 focus:ring-ring" />
        </label>
        <label class="block space-y-1.5 text-sm">
          <span>Password</span>
          <input v-model="password" type="password" autocomplete="current-password" class="h-9 w-full rounded-md border border-input bg-background px-3 outline-none focus:ring-2 focus:ring-ring" />
        </label>
        <p v-if="error" class="text-sm text-destructive">{{ error }}</p>
        <Button class="w-full" type="submit">Sign in</Button>
      </form>
    </section>
  </div>

  <div v-else-if="bootstrap" class="grid min-h-screen bg-background text-foreground" :class="sidebarCollapsed ? 'grid-cols-[68px_1fr]' : 'grid-cols-[240px_1fr]'">
    <aside class="border-r border-border bg-sidebar p-3">
      <div class="mb-5 flex h-10 items-center justify-between">
        <div v-if="!sidebarCollapsed" class="px-2 font-semibold tracking-tight">Koba MCP</div>
        <Button variant="ghost" size="icon" @click="sidebarCollapsed = !sidebarCollapsed">
          <PanelLeftOpen v-if="sidebarCollapsed" class="size-4" />
          <PanelLeftClose v-else class="size-4" />
        </Button>
      </div>
      <nav class="space-y-1">
        <button v-for="[label, icon] in items" :key="label" class="flex h-9 w-full items-center gap-3 rounded-md px-3 text-sm text-muted-foreground transition hover:bg-accent hover:text-foreground" :title="sidebarCollapsed ? label : undefined">
          <component :is="icon" class="size-4 shrink-0" />
          <span v-if="!sidebarCollapsed">{{ label }}</span>
        </button>
      </nav>
    </aside>

    <main class="min-w-0">
      <header class="flex h-14 items-center border-b border-border px-6">
        <div class="text-sm text-muted-foreground">Management Console</div>
        <div class="ml-auto flex items-center gap-2">
          <span class="mr-2 text-xs text-muted-foreground">{{ session.username }}</span>
          <Button variant="ghost" size="icon" @click="toggleTheme">
            <Sun v-if="theme === 'dark'" class="size-4" />
            <Moon v-else class="size-4" />
          </Button>
          <Button variant="outline" size="sm" @click="logout">Sign out</Button>
        </div>
      </header>

      <div class="mx-auto max-w-7xl space-y-6 p-6">
        <div>
          <h1 class="text-2xl font-semibold tracking-tight">Overview</h1>
          <p class="mt-1 text-sm text-muted-foreground">New Vue management surface. Runtime screens migrate here incrementally.</p>
        </div>
        <div class="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          <section v-for="item in bootstrap.navigation" :key="item.id" class="rounded-xl border border-border bg-card p-4 shadow-sm">
            <div class="text-xs font-medium uppercase tracking-wide text-muted-foreground">{{ item.id }}</div>
            <div class="mt-2 text-base font-medium">{{ item.label }}</div>
          </section>
        </div>
        <section class="rounded-xl border border-border bg-card p-5 shadow-sm">
          <div class="text-sm font-medium">Migration mode</div>
          <p class="mt-2 text-sm text-muted-foreground">Starlette Admin remains available while pages move to typed FastAPI endpoints.</p>
          <a class="mt-4 inline-flex text-sm font-medium underline underline-offset-4" :href="bootstrap.legacy_admin_path">Open legacy admin</a>
        </section>
      </div>
    </main>
  </div>

  <div v-else class="grid min-h-screen place-items-center bg-background p-6 text-sm text-destructive">
    {{ error || "Management console unavailable" }}
  </div>
</template>
