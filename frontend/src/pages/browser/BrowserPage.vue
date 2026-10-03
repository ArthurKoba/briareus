<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from "vue"
import { Select } from "ant-design-vue"
import {
  ArrowLeft,
  ChevronDown,
  Circle,
  Code2,
  Ellipsis,
  ExternalLink,
  List,
  LockKeyhole,
  Monitor,
  Plus,
  Puzzle,
  RefreshCw,
  RotateCcw,
  ShieldCheck,
  Trash2,
  X,
} from "lucide-vue-next"
import { useI18n } from "vue-i18n"

import { managementApi } from "@/shared/api/management"
import { eventBus } from "@/shared/events/bus"
import { notifications } from "@/shared/notifications/bus"
import { frontendTelemetry } from "@/shared/telemetry/client"

type Page = {
  page_id: string
  label?: string
  title?: string
  url?: string
  page_agent_access?: boolean
}
type State = {
  selected_page_id?: string
  docked_devtools_page_id?: string
  pages?: Page[]
  agent_access_enabled?: boolean
  developer_access_enabled?: boolean
  developer_access_effective?: boolean
  can_reopen_closed_tab?: boolean
  capabilities?: Record<string, boolean> | string[]
  viewport?: { width?: number; height?: number }
}

const { t } = useI18n()
const state = ref<State>({})
const status = ref<"connecting" | "live" | "disconnected" | "error">("connecting")
const message = ref("")
const addressDraft = ref("")
const addressFocused = ref(false)
const viewportPreset = ref("auto")
const screen = ref<HTMLImageElement | null>(null)
const devtools = ref<HTMLImageElement | null>(null)
const dims = ref({ w: 1440, h: 900 })
const devDims = ref({ w: 1440, h: 900 })
let ws: WebSocket | null = null
let reconnect = 0
let refresh = 0
let lastMove = 0
let devLastMove = 0
let lastSelected = ""

const pages = computed(() => state.value.pages ?? [])
const selectedId = computed(() => state.value.selected_page_id ?? "")
const devId = computed(() => state.value.docked_devtools_page_id ?? "")
const selectedPage = computed(() => pages.value.find((page) => page.page_id === selectedId.value) ?? null)
const live = computed(() => status.value === "live")
function capabilityEnabled(name: string): boolean {
  const capabilities = state.value.capabilities
  if (Array.isArray(capabilities)) return capabilities.includes(name)
  if (capabilities && typeof capabilities === "object") return capabilities[name] === true
  return false
}
const canSetViewport = computed(() => capabilityEnabled("set_viewport"))
const viewportOptions = computed(() => [
  { label: t("browser.automatic"), value: "auto" },
  { label: "1280 × 720", value: "1280x720" },
  { label: "1440 × 900", value: "1440x900" },
  { label: "1920 × 1080", value: "1920x1080" },
  { label: "2560 × 1440", value: "2560x1440" },
])

function send(payload: Record<string, unknown>): void {
  if (ws?.readyState === WebSocket.OPEN) ws.send(JSON.stringify(payload))
}

function syncAddress(): void {
  const page = selectedPage.value
  if (!page) return
  if (!addressFocused.value || page.page_id !== lastSelected) addressDraft.value = page.url ?? ""
  lastSelected = page.page_id
}

async function connect(): Promise<void> {
  if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) return
  status.value = "connecting"
  message.value = String(t("browser.connecting"))
  try {
    const scheme = location.protocol === "https:" ? "wss:" : "ws:"
    ws = new WebSocket(`${scheme}//${location.host}/api/browser/operator/ws`)
    ws.onopen = () => {
      frontendTelemetry.websocket("connected", "browser.operator", "websocket")
    }
    ws.onclose = (event) => {
      ws = null
      status.value = "disconnected"
      frontendTelemetry.websocket("disconnected", "browser.operator", "websocket")
      if (event.code === 4401) {
        message.value = String(t("browser.authorizationExpired"))
        window.dispatchEvent(new CustomEvent("management:auth-expired"))
        return
      }
      if (event.code === 4403) {
        status.value = "error"
        message.value = String(t("browser.connectionFailed"))
        notifications.error(String(t("notifications.websocketError")), message.value)
        return
      }
      message.value = String(t("browser.reconnecting"))
      clearTimeout(reconnect)
      reconnect = window.setTimeout(connect, 1000)
    }
    ws.onerror = () => {
      status.value = "error"
      message.value = String(t("browser.connectionFailed"))
      frontendTelemetry.websocket("error", "browser.operator")
      notifications.error(String(t("notifications.websocketError")), message.value)
    }
    ws.onmessage = async (event) => {
      const payload = JSON.parse(event.data)
      if (payload.type === "state") {
        state.value = payload
        if (payload.viewport?.width && payload.viewport?.height) dims.value = { w: payload.viewport.width, h: payload.viewport.height }
        status.value = "live"
        message.value = ""
        eventBus.publishMock("browser.runtime", "state", {
          pages: Array.isArray(payload.pages) ? payload.pages.length : 0,
          selected_page_id: payload.selected_page_id ?? null,
        })
        await nextTick()
        syncAddress()
      } else if (payload.type === "frame") {
        const target = payload.page_id === selectedId.value ? screen.value : payload.page_id === devId.value ? devtools.value : null
        if (target) target.src = `data:image/jpeg;base64,${payload.data}`
        const dimension = payload.page_id === selectedId.value ? dims : devDims
        if (payload.metadata) dimension.value = {
          w: payload.metadata.deviceWidth ?? dimension.value.w,
          h: payload.metadata.deviceHeight ?? dimension.value.h,
        }
      } else if (payload.type === "error") {
        status.value = "error"
        message.value = payload.message ?? String(t("browser.connectionFailed"))
        notifications.error(String(t("notifications.websocketError")), message.value)
      }
    }
  } catch (caught) {
    status.value = "error"
    message.value = caught instanceof Error ? caught.message : String(t("browser.connectionFailed"))
    frontendTelemetry.error("browser.connect", caught)
    notifications.error(String(t("notifications.websocketError")), message.value)
    clearTimeout(reconnect)
    reconnect = window.setTimeout(connect, 3000)
  }
}

function navigate(): void {
  const value = addressDraft.value.trim()
  if (!value) return
  send({ type: "navigate", url: value })
  addressFocused.value = false
}
function selectPage(pageId: string): void { send({ type: "select_page", page_id: pageId }) }
function closePage(pageId?: string): void {
  if (pageId && pageId !== selectedId.value) {
    send({ type: "select_page", page_id: pageId })
    window.setTimeout(() => send({ type: "close_page" }), 50)
  } else send({ type: "close_page" })
}
function newPage(): void { send({ type: "new_page" }) }
function developer(): void {
  const allow = state.value.developer_access_enabled !== true
  if (allow && !confirm(String(t("browser.developerConfirm")))) return
  send({ type: "set_developer_access", allowed: allow })
}
async function setViewport(value: string): Promise<void> {
  viewportPreset.value = value
  if (!canSetViewport.value || value === "auto" || !selectedId.value) return
  const [width, height] = value.split("x").map(Number)
  if (!width || !height) return
  try {
    await managementApi.setBrowserViewport(selectedId.value, width, height)
    dims.value = { w: width, h: height }
    send({ type: "refresh_state" })
    frontendTelemetry.event("browser.viewport_change", { page_id: selectedId.value, width, height })
  } catch (caught) {
    frontendTelemetry.error("browser.viewport_change_failed", caught, { page_id: selectedId.value, width, height })
  }
}
function cleanApp(): void {
  if (confirm(String(t("browser.cleanAppConfirm")))) send({ type: "clean_app" })
}
function cleanBrowser(): void {
  if (confirm(String(t("browser.cleanBrowserConfirm")))) send({ type: "clean_browser" })
}
function pointer(img: HTMLImageElement | null, page: string, d: { w: number; h: number }, event: MouseEvent, type: string, button = "none", click_count = 0): void {
  if (!img?.src || !page) return
  const rect = img.getBoundingClientRect()
  send({ type: "mouse", page_id: page, event: type, x: (event.clientX - rect.left) * d.w / rect.width, y: (event.clientY - rect.top) * d.h / rect.height, button, click_count })
}
function wheel(img: HTMLImageElement | null, page: string, d: { w: number; h: number }, event: WheelEvent): void {
  if (!img?.src || !page) return
  const rect = img.getBoundingClientRect()
  send({ type: "mouse", page_id: page, event: "mouseWheel", x: (event.clientX - rect.left) * d.w / rect.width, y: (event.clientY - rect.top) * d.h / rect.height, delta_x: event.deltaX, delta_y: event.deltaY })
  event.preventDefault()
}
function key(page: string, event: KeyboardEvent): void {
  if (!page) return
  if (event.ctrlKey && event.shiftKey && event.key.toLowerCase() === "t") {
    send({ type: "reopen_closed_page" })
    event.preventDefault()
    return
  }
  if (event.ctrlKey || event.altKey || event.metaKey || event.key.length > 1) {
    const parts: string[] = []
    if (event.ctrlKey) parts.push("Control")
    if (event.altKey) parts.push("Alt")
    if (event.metaKey) parts.push("Meta")
    if (event.shiftKey && event.key.length > 1) parts.push("Shift")
    parts.push(event.key)
    send({ type: "key", page_id: page, key: parts.join("+") })
  } else send({ type: "text", page_id: page, text: event.key })
  event.preventDefault()
}
function now(): number { return window.performance.now() }
function mouseButton(event: MouseEvent): string { return event.button === 2 ? "right" : event.button === 1 ? "middle" : "left" }

onMounted(() => {
  void connect()
  refresh = window.setInterval(() => send({ type: "refresh_state" }), 1500)
})
onBeforeUnmount(() => {
  clearInterval(refresh)
  clearTimeout(reconnect)
  ws?.close()
})
</script>

<template>
  <div class="overflow-hidden rounded-xl border border-border/70 bg-card shadow-sm">
    <div class="flex h-10 items-end gap-1 border-b border-border/70 bg-muted/60 px-2 pt-1">
      <details class="relative mb-1">
        <summary class="grid size-7 cursor-pointer list-none place-items-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground [&::-webkit-details-marker]:hidden" :title="String(t('browser.allTabs'))">
          <List class="size-4" />
        </summary>
        <div class="absolute left-0 top-8 z-50 w-80 rounded-xl border border-border bg-popover p-2 shadow-xl">
          <button
            v-for="page in pages"
            :key="page.page_id"
            class="flex w-full items-center gap-2 rounded-md px-2 py-2 text-left text-xs hover:bg-accent"
            :class="page.page_id === selectedId && 'bg-accent'"
            @click="selectPage(page.page_id)"
          >
            <Circle class="size-2.5 shrink-0" :class="page.page_id === selectedId ? 'fill-emerald-500 text-emerald-500' : 'fill-muted-foreground text-muted-foreground'" />
            <span class="min-w-0 flex-1 truncate">{{ page.title || page.label || t("browser.untitled") }}</span>
            <span class="max-w-28 truncate text-[10px] text-muted-foreground">{{ page.url }}</span>
          </button>
        </div>
      </details>

      <div class="flex min-w-0 flex-1 gap-1 overflow-x-auto">
        <button
          v-for="page in pages"
          :key="page.page_id"
          class="group flex h-8 min-w-32 max-w-52 flex-1 items-center gap-2 rounded-t-lg border border-transparent px-2 text-left text-[11px]"
          :class="page.page_id === selectedId ? 'border-border/70 border-b-card bg-card text-foreground' : 'text-muted-foreground hover:bg-accent/70 hover:text-foreground'"
          @click="selectPage(page.page_id)"
        >
          <span class="min-w-0 flex-1 truncate">{{ page.title || page.label || t("browser.untitled") }}</span>
          <span class="grid size-5 shrink-0 place-items-center rounded hover:bg-muted" @click.stop="closePage(page.page_id)"><X class="size-3" /></span>
        </button>
      </div>
      <button class="mb-1 grid size-7 shrink-0 place-items-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground" :title="String(t('browser.newTab'))" @click="newPage"><Plus class="size-4" /></button>
    </div>

    <div class="flex h-11 items-center gap-1.5 border-b border-border/70 bg-card px-2">
      <button class="browser-tool" :disabled="!live" :title="String(t('browser.back'))" @click="send({type:'back'})"><ArrowLeft class="size-4" /></button>
      <button class="browser-tool" :disabled="!live" :title="String(t('browser.reload'))" @click="send({type:'reload'})"><RefreshCw class="size-4" /></button>
      <form class="mx-1 flex min-w-0 flex-1 items-center rounded-full border border-border/70 bg-muted/55 px-3 focus-within:border-ring" @submit.prevent="navigate">
        <LockKeyhole class="mr-2 size-3.5 shrink-0 text-muted-foreground" />
        <input
          v-model="addressDraft"
          class="h-8 min-w-0 flex-1 bg-transparent text-xs outline-none"
          :placeholder="t('browser.addressPlaceholder')"
          @focus="addressFocused = true"
          @blur="addressFocused = false"
        />
        <button type="submit" class="grid size-6 place-items-center rounded-full text-muted-foreground hover:bg-accent hover:text-foreground" :title="String(t('browser.go'))"><ExternalLink class="size-3.5" /></button>
      </form>
      <button class="browser-tool" :disabled="!live" :title="String(t('browser.extensions'))" @click="send({type:'new_page',url:'chrome://extensions/'})"><Puzzle class="size-4" /></button>
      <button class="browser-tool" :disabled="!live" title="DevTools" @click="send({type:'open_docked_devtools',panel:'elements'})"><Code2 class="size-4" /></button>
      <span class="mx-1 h-5 w-px bg-border" />
      <span class="inline-flex items-center gap-1 text-[10px]" :class="live ? 'text-emerald-500' : status === 'error' ? 'text-destructive' : 'text-amber-500'" :title="message || status"><Circle class="size-2.5 fill-current" /></span>
      <details class="relative">
        <summary class="browser-tool cursor-pointer list-none [&::-webkit-details-marker]:hidden" :title="String(t('browser.more'))"><Ellipsis class="size-4" /></summary>
        <div class="absolute right-0 top-9 z-50 w-72 rounded-xl border border-border bg-popover p-2 text-xs shadow-xl">
          <button class="browser-menu-row" @click="send({type:'reopen_closed_page'})"><RotateCcw class="size-4" />{{ t("browser.reopen") }}</button>
          <button class="browser-menu-row" @click="send({type:'open_devtools',panel:'elements'})"><Code2 class="size-4" />{{ t("browser.devtoolsTab") }}</button>
          <button class="browser-menu-row" @click="send({type:'set_agent_access',allowed:state.agent_access_enabled===false})"><ShieldCheck class="size-4" />{{ t("browser.agents") }}: {{ state.agent_access_enabled === false ? t("browser.blocked") : t("browser.on") }}</button>
          <button class="browser-menu-row" @click="developer"><Code2 class="size-4" />{{ t("browser.developer") }}: {{ state.developer_access_effective ? t("browser.on") : state.developer_access_enabled ? t("browser.armed") : t("browser.off") }}</button>
          <div class="my-1 border-t border-border" />
          <div class="flex items-center justify-between gap-2 px-2 py-1.5"><span class="inline-flex items-center gap-2"><Monitor class="size-4" />{{ t("browser.viewport") }}</span><Select :value="viewportPreset" :options="viewportOptions" class="w-32" size="small" :disabled="!live || !canSetViewport" @change="setViewport(String($event))" /></div>
          <div class="my-1 border-t border-border" />
          <button class="browser-menu-row" @click="cleanApp"><Trash2 class="size-4" />{{ t("browser.cleanApp") }}</button>
          <button class="browser-menu-row text-destructive" @click="cleanBrowser"><Trash2 class="size-4" />{{ t("browser.cleanBrowser") }}</button>
        </div>
      </details>
    </div>

    <div class="grid" :class="devId ? 'xl:grid-cols-[minmax(0,1fr)_minmax(360px,.65fr)]' : ''">
      <div class="browser-screen relative min-h-[560px] border-0">
        <img
          ref="screen"
          tabindex="0"
          alt="Live Chromium tab"
          @mousedown="pointer(screen, selectedId, dims, $event, 'mousePressed', mouseButton($event), 1)"
          @mouseup="pointer(screen, selectedId, dims, $event, 'mouseReleased', mouseButton($event), 1)"
          @mousemove="event => { const n=now(); if(n-lastMove>33){ lastMove=n; pointer(screen, selectedId, dims, event, 'mouseMoved') } }"
          @wheel="wheel(screen, selectedId, dims, $event)"
          @keydown="key(selectedId, $event)"
          @contextmenu.prevent
        />
        <span class="pointer-events-none absolute bottom-2 right-2 rounded bg-black/65 px-2 py-1 text-[10px] text-white/70">{{ dims.w }}×{{ dims.h }}</span>
      </div>
      <div v-if="devId" class="relative border-l border-border/70 bg-[#090909]">
        <button class="absolute right-2 top-2 z-10 grid size-7 place-items-center rounded bg-black/60 text-white/70 hover:text-white" @click="send({type:'close_docked_devtools'})"><X class="size-4" /></button>
        <div class="browser-screen min-h-[560px] border-0">
          <img
            ref="devtools"
            tabindex="0"
            alt="Docked DevTools"
            @mousedown="pointer(devtools, devId, devDims, $event, 'mousePressed', mouseButton($event), 1)"
            @mouseup="pointer(devtools, devId, devDims, $event, 'mouseReleased', mouseButton($event), 1)"
            @mousemove="event => { const n=now(); if(n-devLastMove>33){ devLastMove=n; pointer(devtools, devId, devDims, event, 'mouseMoved') } }"
            @wheel="wheel(devtools, devId, devDims, $event)"
            @keydown="key(devId, $event)"
            @contextmenu.prevent
          />
        </div>
      </div>
    </div>
  </div>
</template>
