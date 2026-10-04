<script setup lang="ts">
import { computed, ref } from "vue"
import { Braces, Check, Copy, Text } from "lucide-vue-next"
import { useI18n } from "vue-i18n"

const props = defineProps<{ value: string | unknown }>()
const { t } = useI18n()
const mode = ref<"formatted" | "raw">("formatted")
const copied = ref(false)
const DISPLAY_LIMIT = 120_000
const MAX_NESTED_DEPTH = 3

type JsonValue = null | boolean | number | string | JsonValue[] | { [key: string]: JsonValue }
type Token = { text: string; kind: "plain" | "key" | "string" | "number" | "boolean" | "null" }

const raw = computed(() => typeof props.value === "string" ? props.value : JSON.stringify(props.value, null, 2))

function parseNested(value: unknown, depth = 0): unknown {
  if (depth >= MAX_NESTED_DEPTH) return value
  if (Array.isArray(value)) return value.map(item => parseNested(item, depth + 1))
  if (value && typeof value === "object") {
    return Object.fromEntries(Object.entries(value as Record<string, unknown>).map(([key, item]) => [key, parseNested(item, depth + 1)]))
  }
  if (typeof value !== "string") return value
  const candidate = value.trim()
  if (candidate.length < 2 || candidate.length > DISPLAY_LIMIT || !["{", "["].includes(candidate[0] ?? "")) return value
  try {
    const parsed = JSON.parse(candidate) as unknown
    return parsed && typeof parsed === "object" ? parseNested(parsed, depth + 1) : value
  } catch {
    return value
  }
}

const parsed = computed(() => {
  if (typeof props.value !== "string") return { structured: true, value: parseNested(props.value) }
  const candidate = props.value.trim()
  if (!candidate) return { structured: false, value: "" }
  try { return { structured: true, value: parseNested(JSON.parse(candidate) as unknown) } }
  catch { return { structured: false, value: props.value } }
})

const formatted = computed(() => parsed.value.structured ? JSON.stringify(parsed.value.value, null, 2) : String(parsed.value.value))
const display = computed(() => mode.value === "raw" ? raw.value : formatted.value)
const truncated = computed(() => display.value.length > DISPLAY_LIMIT)
const visible = computed(() => truncated.value ? `${display.value.slice(0, DISPLAY_LIMIT)}\n…` : display.value)

const tokenPattern = /("(?:\\u[a-fA-F0-9]{4}|\\[^u]|[^\\"])*"\s*:)|("(?:\\u[a-fA-F0-9]{4}|\\[^u]|[^\\"])*")|\b(true|false)\b|\bnull\b|-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?/g
const tokens = computed<Token[]>(() => {
  if (mode.value === "raw" || !parsed.value.structured) return [{ text: visible.value || "—", kind: "plain" }]
  const source = visible.value || "—"
  const result: Token[] = []
  let last = 0
  for (const match of source.matchAll(tokenPattern)) {
    const index = match.index ?? 0
    if (index > last) result.push({ text: source.slice(last, index), kind: "plain" })
    const text = match[0]
    const kind: Token["kind"] = match[1] ? "key" : match[2] ? "string" : match[3] ? "boolean" : text === "null" ? "null" : "number"
    result.push({ text, kind })
    last = index + text.length
  }
  if (last < source.length) result.push({ text: source.slice(last), kind: "plain" })
  return result
})

async function copyRaw(): Promise<void> {
  if (!navigator.clipboard) return
  await navigator.clipboard.writeText(raw.value)
  copied.value = true
  window.setTimeout(() => { copied.value = false }, 1200)
}
</script>

<template>
  <div class="overflow-hidden rounded-lg border border-border/60 bg-muted/40">
    <div class="flex items-center justify-between gap-2 border-b border-border/60 px-2 py-1.5">
      <div class="flex items-center gap-1">
        <button type="button" class="rounded px-2 py-1 text-[11px]" :class="mode === 'formatted' ? 'bg-background text-foreground shadow-sm' : 'text-muted-foreground hover:text-foreground'" @click="mode = 'formatted'"><Braces class="mr-1 inline size-3" />{{ t("jsonView.formatted") }}</button>
        <button type="button" class="rounded px-2 py-1 text-[11px]" :class="mode === 'raw' ? 'bg-background text-foreground shadow-sm' : 'text-muted-foreground hover:text-foreground'" @click="mode = 'raw'"><Text class="mr-1 inline size-3" />{{ t("jsonView.raw") }}</button>
      </div>
      <button type="button" class="inline-flex items-center gap-1 rounded px-2 py-1 text-[11px] text-muted-foreground hover:bg-background hover:text-foreground" @click="copyRaw"><Check v-if="copied" class="size-3 text-emerald-500" /><Copy v-else class="size-3" />{{ copied ? t("jsonView.copied") : t("jsonView.copy") }}</button>
    </div>
    <pre class="max-h-[480px] overflow-auto p-3 font-mono text-xs leading-5 whitespace-pre"><code><template v-for="(token, index) in tokens" :key="index"><span :class="{
      'text-sky-600 dark:text-sky-300': token.kind === 'key',
      'text-emerald-600 dark:text-emerald-300': token.kind === 'string',
      'text-amber-600 dark:text-amber-300': token.kind === 'number',
      'text-violet-600 dark:text-violet-300': token.kind === 'boolean',
      'text-rose-500': token.kind === 'null',
    }">{{ token.text }}</span></template></code></pre>
    <div v-if="truncated" class="border-t border-border/60 px-3 py-2 text-[11px] text-muted-foreground">{{ t("jsonView.truncated") }}</div>
  </div>
</template>
