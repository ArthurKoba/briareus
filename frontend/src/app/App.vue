<script setup lang="ts">
import { computed, defineAsyncComponent, onMounted, ref } from "vue"
import { Activity, AppWindow, Blocks, Bot, Database, FileText, Github, Moon, PanelLeftClose, PanelLeftOpen, Settings, Sun, TerminalSquare } from "lucide-vue-next"
import { managementApi, type ManagementBootstrap, type SessionState } from "@/shared/api/management"
import { useUiPreferences } from "@/shared/lib/preferences"
import Button from "@/shared/ui/Button.vue"

const OverviewPage=defineAsyncComponent(()=>import("@/pages/OverviewPage.vue"))
const AccountsPage=defineAsyncComponent(()=>import("@/pages/AccountsPage.vue"))
const CallsPage=defineAsyncComponent(()=>import("@/pages/CallsPage.vue"))
const FilesPage=defineAsyncComponent(()=>import("@/pages/FilesPage.vue"))
const TerminalPage=defineAsyncComponent(()=>import("@/pages/TerminalPage.vue"))
const BrowserPage=defineAsyncComponent(()=>import("@/pages/BrowserPage.vue"))
const AnalysisPage=defineAsyncComponent(()=>import("@/pages/AnalysisPage.vue"))
const OAuthPage=defineAsyncComponent(()=>import("@/pages/OAuthPage.vue"))
const SettingsPage=defineAsyncComponent(()=>import("@/pages/SettingsPage.vue"))

const session=ref<SessionState|null>(null), bootstrap=ref<ManagementBootstrap|null>(null), loading=ref(true), error=ref(""), username=ref(""), password=ref("")
const activePage=ref("overview")
const {theme,sidebarCollapsed}=useUiPreferences()
const nav=[
  {id:"overview",label:"Overview",icon:Activity,component:OverviewPage},
  {id:"accounts",label:"Accounts",icon:Github,component:AccountsPage},
  {id:"calls",label:"MCP Calls",icon:Blocks,component:CallsPage},
  {id:"files",label:"Files",icon:FileText,component:FilesPage},
  {id:"terminal",label:"Terminal",icon:TerminalSquare,component:TerminalPage},
  {id:"browser",label:"Browser",icon:AppWindow,component:BrowserPage},
  {id:"analysis",label:"Analysis",icon:Database,component:AnalysisPage},
  {id:"oauth",label:"OAuth Sessions",icon:Bot,component:OAuthPage},
  {id:"settings",label:"Settings",icon:Settings,component:SettingsPage},
]
const current=computed(()=>nav.find(item=>item.id===activePage.value)??nav[0])
function select(id:string){activePage.value=id;history.replaceState(null,"",`#${id}`)}
function readHash(){const id=location.hash.slice(1);if(nav.some(item=>item.id===id))activePage.value=id}
async function load(){loading.value=true;error.value="";try{session.value=await managementApi.session();bootstrap.value=session.value.authenticated?await managementApi.bootstrap():null}catch(e){error.value=e instanceof Error?e.message:"Unable to load management console"}finally{loading.value=false}}
async function login(){error.value="";try{session.value=await managementApi.login(username.value,password.value);password.value="";bootstrap.value=await managementApi.bootstrap()}catch(e){error.value=e instanceof Error?e.message:"Invalid username or password"}}
async function logout(){session.value=await managementApi.logout();bootstrap.value=null}
function toggleTheme(){theme.value=theme.value==="dark"?"light":"dark"}
onMounted(()=>{readHash();window.addEventListener("hashchange",readHash);load()})
</script>
<template>
  <div v-if="loading" class="grid min-h-screen place-items-center bg-background text-sm text-muted-foreground">Loading management…</div>
  <div v-else-if="!session?.authenticated" class="grid min-h-screen place-items-center bg-muted/30 p-6"><section class="w-full max-w-sm rounded-xl border border-border bg-card p-6 shadow-sm"><h1 class="text-xl font-semibold">MCP Management</h1><p class="mt-1 text-sm text-muted-foreground">Sign in to the management console.</p><form class="mt-6 space-y-4" @submit.prevent="login"><label class="block space-y-1.5 text-sm"><span>Username</span><input v-model="username" autocomplete="username" class="field" /></label><label class="block space-y-1.5 text-sm"><span>Password</span><input v-model="password" type="password" autocomplete="current-password" class="field" /></label><p v-if="error" class="text-sm text-destructive">{{error}}</p><Button class="w-full" type="submit">Sign in</Button></form></section></div>
  <div v-else-if="bootstrap" class="grid min-h-screen bg-background text-foreground" :class="sidebarCollapsed?'grid-cols-[68px_1fr]':'grid-cols-[240px_1fr]'">
    <aside class="sticky top-0 h-screen border-r border-border bg-sidebar p-3"><div class="mb-5 flex h-10 items-center justify-between"><div v-if="!sidebarCollapsed" class="px-2 font-semibold tracking-tight">Koba MCP</div><Button variant="ghost" size="icon" @click="sidebarCollapsed=!sidebarCollapsed"><PanelLeftOpen v-if="sidebarCollapsed" class="size-4"/><PanelLeftClose v-else class="size-4"/></Button></div><nav class="space-y-1"><button v-for="item in nav" :key="item.id" class="flex h-9 w-full items-center gap-3 rounded-md px-3 text-sm transition" :class="activePage===item.id?'bg-accent text-foreground':'text-muted-foreground hover:bg-accent hover:text-foreground'" :title="sidebarCollapsed?item.label:undefined" @click="select(item.id)"><component :is="item.icon" class="size-4 shrink-0"/><span v-if="!sidebarCollapsed">{{item.label}}</span></button></nav></aside>
    <main class="min-w-0"><header class="sticky top-0 z-20 flex h-14 items-center border-b border-border bg-background/90 px-6 backdrop-blur"><div class="text-sm text-muted-foreground">{{current.label}}</div><div class="ml-auto flex items-center gap-2"><span class="mr-2 text-xs text-muted-foreground">{{session.username}}</span><Button variant="ghost" size="icon" @click="toggleTheme"><Sun v-if="theme==='dark'" class="size-4"/><Moon v-else class="size-4"/></Button><Button variant="outline" size="sm" @click="logout">Sign out</Button></div></header><div class="mx-auto max-w-[1600px] p-6"><component :is="current.component" /></div></main>
  </div>
  <div v-else class="grid min-h-screen place-items-center bg-background p-6 text-sm text-destructive">{{error||"Management console unavailable"}}</div>
</template>
