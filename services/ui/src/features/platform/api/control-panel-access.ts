/** Browser reads ONLY the same-origin Control Panel API.
 * The UI does not select or configure the authentication provider,
 * hold service credentials, or manage external identity sessions.
 * The Backend BFF is the sole owner of authorization initiation and session.
 */
const CURRENT_USER_ROUTE = "/api/platform/me"

export type ControlPanelAccessState = "checking" | "signed_out" | "denied" | "unverified" | "unavailable"

/** Connectivity is not an authenticated User or login-readiness assertion.
 * A 200 without a typed, accepted User projection is not a signed-in User.
 * A 401 is ordinary signed-out behavior; 403 is a permission denial.
 * A reachable BFF does not prove that a login/start route exists.
 */
export async function checkControlPanelAccess(signal: AbortSignal): Promise<Exclude<ControlPanelAccessState, "checking">> {
  if (signal.aborted) return "unavailable"
  const timeout = new AbortController()
  const cancel = () => timeout.abort()
  const deadline = setTimeout(cancel, 8000)
  signal.addEventListener("abort", cancel, { once: true })
  try {
    const response = await fetch(CURRENT_USER_ROUTE, {
      method: "GET",
      signal: timeout.signal,
      mode: "same-origin",
      credentials: "same-origin",
      cache: "no-store",
      redirect: "error",
      referrerPolicy: "no-referrer",
      headers: { Accept: "application/json" },
    })
    // Never parse a possible User body without an accepted BFF DTO.
    if (response.status === 401) return "signed_out"
    if (response.status === 403) return "denied"
    if (response.status === 200) return "unverified"
    return "unavailable"
  } catch { return "unavailable" }
  finally {
    clearTimeout(deadline)
    signal.removeEventListener("abort", cancel)
  }
}
