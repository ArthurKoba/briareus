import { reactive, watch } from "vue"

export interface TabWorkspaceState {
  realtimeEnabled: boolean
  topicOverrides: Record<string, boolean | null>
}

const STORAGE_KEY = "mcp-bridge:tab-workspace"
const defaults: TabWorkspaceState = {
  realtimeEnabled: true,
  topicOverrides: {},
}

function load(): TabWorkspaceState {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY)
    if (!raw) return { ...defaults, topicOverrides: {} }
    const parsed = JSON.parse(raw) as Partial<TabWorkspaceState>
    return {
      realtimeEnabled: parsed.realtimeEnabled ?? true,
      topicOverrides: parsed.topicOverrides && typeof parsed.topicOverrides === "object" ? parsed.topicOverrides : {},
    }
  } catch {
    return { ...defaults, topicOverrides: {} }
  }
}

export const tabWorkspace = reactive<TabWorkspaceState>(load())

watch(tabWorkspace, (value) => {
  sessionStorage.setItem(STORAGE_KEY, JSON.stringify(value))
}, { deep: true })

export function topicRealtimeEnabled(topic: string): boolean {
  const override = tabWorkspace.topicOverrides[topic]
  return override === null || override === undefined ? tabWorkspace.realtimeEnabled : override
}
