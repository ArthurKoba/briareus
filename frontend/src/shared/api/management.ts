import { runtimeConfig } from "@/shared/config/runtime"

export interface SessionState {
  authenticated: boolean
  username: string | null
}

export interface ManagementBootstrap {
  product: string
  environment: string
  legacy_admin_path: string
  navigation: Array<{ id: string; label: string; enabled: boolean }>
}

const previewBootstrap: ManagementBootstrap = {
  product: "MCP Management",
  environment: "frontend-preview",
  legacy_admin_path: "#",
  navigation: [
    { id: "overview", label: "Overview", enabled: true },
    { id: "accounts", label: "Accounts", enabled: true },
    { id: "calls", label: "MCP Calls", enabled: true },
    { id: "files", label: "Files", enabled: true },
    { id: "terminal", label: "Terminal", enabled: true },
    { id: "browser", label: "Browser", enabled: true },
    { id: "analysis", label: "Analysis", enabled: true },
    { id: "oauth", label: "OAuth Sessions", enabled: true },
    { id: "settings", label: "Settings", enabled: true },
  ],
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    ...init,
  })
  if (!response.ok) {
    throw new Error("Management API request failed: " + response.status)
  }
  return response.json() as Promise<T>
}

export const managementApi = {
  session: (): Promise<SessionState> =>
    runtimeConfig.preview
      ? Promise.resolve({ authenticated: true, username: "preview" })
      : request<SessionState>("/api/session"),
  login: (username: string, password: string): Promise<SessionState> =>
    runtimeConfig.preview
      ? Promise.resolve({ authenticated: true, username: username || "preview" })
      : request<SessionState>("/api/login", {
          method: "POST",
          body: JSON.stringify({ username, password }),
        }),
  logout: (): Promise<SessionState> =>
    runtimeConfig.preview
      ? Promise.resolve({ authenticated: false, username: null })
      : request<SessionState>("/api/logout", { method: "POST", body: "{}" }),
  bootstrap: (): Promise<ManagementBootstrap> =>
    runtimeConfig.preview
      ? Promise.resolve(previewBootstrap)
      : request<ManagementBootstrap>("/api/bootstrap"),
}
