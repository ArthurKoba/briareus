/** Browser reads ONLY the same-origin Control Panel API.
 * The UI does not select or configure the authentication provider,
 * hold service credentials, or manage external identity sessions.
 * The Backend BFF is the sole owner of authorization initiation and session.
 */
const CURRENT_USER_ROUTE = "/api/platform/me"

export type ControlPanelAccessState = "checking" | "reachable" | "unavailable"

/** Connectivity is not an authenticated User or login-readiness assertion.
 * HTTP 200 may be stale/untrusted without a verified BFF User projection.
 * HTTP 401/403 are expected before a human session and prove only that
 * the API is answering, not that a session-start route is available.
 */
export async function checkControlPanelAccess(signal: AbortSignal): Promise<Exclude<ControlPanelAccessState, "checking">> {
  try {
    const response = await fetch(CURRENT_USER_ROUTE, {
      method: "GET",
      signal,
      mode: "same-origin",
      credentials: "same-origin",
      cache: "no-store",
      redirect: "error",
      referrerPolicy: "no-referrer",
      headers: { Accept: "application/json" },
    })
    // Never parse response bodies or assume user identity/authorization.
    return [200, 401, 403].includes(response.status) ? "reachable" : "unavailable"
  } catch { return "unavailable" }
}
