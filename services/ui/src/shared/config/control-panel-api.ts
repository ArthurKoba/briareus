/** Canonical, versioned browser-facing Control Panel API namespace.
 * Fixed same-origin path: never infer protocol/version from provider metadata,
 * cookies, the current Project or a browser-controlled URL.
 * Backend owns every route. No fallback to retired, unversioned API paths.
 */
export const CONTROL_PANEL_API_V1 = "/api/v1" as const
export const CONTROL_PANEL_AUTH_API = `${CONTROL_PANEL_API_V1}/auth` as const
