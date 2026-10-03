export interface ManagementUiRuntimeConfig {
  preview: boolean
}

declare global {
  interface Window {
    __MCP_MANAGEMENT_UI_CONFIG__?: Partial<ManagementUiRuntimeConfig>
  }
}

export const runtimeConfig: ManagementUiRuntimeConfig = {
  preview: window.__MCP_MANAGEMENT_UI_CONFIG__?.preview ?? true,
}
