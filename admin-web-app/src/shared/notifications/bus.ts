import { readonly, ref } from "vue"

export type NotificationLevel = "info" | "success" | "warning" | "error"
export interface AppNotification {
  id: number
  level: NotificationLevel
  title: string
  description?: string
  actionLabel?: string
  action?: () => void
  timeoutMs?: number
  dedupeKey?: string
  count?: number
}

const items = ref<AppNotification[]>([])
let nextId = 1
const timers = new Map<number, number>()

function remove(id: number): void {
  items.value = items.value.filter((item) => item.id !== id)
  const timer = timers.get(id)
  if (timer) window.clearTimeout(timer)
  timers.delete(id)
}

function arm(item: AppNotification): void {
  const old = timers.get(item.id)
  if (old) window.clearTimeout(old)
  const timeout = item.timeoutMs ?? (item.level === "error" ? 8000 : 4000)
  if (timeout > 0) timers.set(item.id, window.setTimeout(() => remove(item.id), timeout))
}

function push(value: Omit<AppNotification, "id">): number {
  const dedupeKey = value.dedupeKey ?? `${value.level}:${value.title}:${value.description ?? ""}`
  const existing = items.value.find((item) => item.dedupeKey === dedupeKey)
  if (existing) {
    existing.count = (existing.count ?? 1) + 1
    existing.description = value.description
    existing.action = value.action
    existing.actionLabel = value.actionLabel
    arm(existing)
    return existing.id
  }
  const item: AppNotification = { id: nextId++, count: 1, dedupeKey, ...value }
  items.value.push(item)
  if (items.value.length > 5) remove(items.value[0]!.id)
  arm(item)
  return item.id
}

function clearAll(): void {
  for (const timer of timers.values()) window.clearTimeout(timer)
  timers.clear()
  items.value = []
}

export const notifications = {
  clearAll,
  items: readonly(items),
  push,
  remove,
  info: (title: string, description?: string) => push({ level: "info", title, description }),
  success: (title: string, description?: string) => push({ level: "success", title, description }),
  warning: (title: string, description?: string) => push({ level: "warning", title, description }),
  error: (title: string, description?: string, dedupeKey?: string) => push({ level: "error", title, description, dedupeKey }),
}
