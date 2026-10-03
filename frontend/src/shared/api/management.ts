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
  session: () => request<SessionState>("/admin/api/session"),
  login: (username: string, password: string) =>
    request<SessionState>("/admin/api/login", {
      method: "POST",
      body: JSON.stringify({ username, password }),
    }),
  logout: () =>
    request<SessionState>("/admin/api/logout", { method: "POST", body: "{}" }),
  bootstrap: () => request<ManagementBootstrap>("/admin/api/bootstrap"),
}
