import { knownPlatformPage, type PlatformPageId } from "./platform-navigation"

/** Navigation to presentation-only screens. Never confers server capabilities.
 * Without a fresh verified Rauthy-bound Platform User, only /home is usable.
 */
export const OIDC_PRESENTATION_PAGES: readonly PlatformPageId[] = [
  "home", "mcp", "users", "teams", "projects", "agents", "sessions",
  "integrations", "variables", "dashboard", "calls", "oauth", "files",
  "terminal", "browser-managed", "browser-external", "analysis", "settings",
]
export function resolveOidcView(hash: string, hasVerifiedUser: boolean): PlatformPageId {
  if(!hasVerifiedUser)return "home"
  const [root,child] = hash.replace(/^#/, "").split("/")
  if(root!=="platform"||!child||!knownPlatformPage(child))return "home"
  return OIDC_PRESENTATION_PAGES.includes(child)?child:"home"
}


/** UX visibility only: the server must authorize each AgentSession operation
 * again. This count never mints a grant or opens a protected route alone.
 */
export function countPresentableAgentSessionProjects(
  projects: readonly {permissions:readonly string[]}[],
):number {
  return projects.filter(project=>project.permissions.includes("use_resources")||
    project.permissions.includes("approve_agent_session")).length
}


/** Select the first session-capable Project for the initial MVP workspace.
 * This only chooses a tab; every BFF read/write independently proves scope.
 */
export function preferredAgentSessionProjectId(
  projects: readonly {id:string;permissions:readonly string[]}[],
):string|null {
  return projects.find(project=>project.permissions.includes("use_resources"))?.id ??
    projects.find(project=>project.permissions.includes("approve_agent_session"))?.id ??
    projects[0]?.id??null
}


/** Reconcile a user-selected Project against each freshly verified owner proof.
 * Keep only a still-visible session-capable choice; revoked access must not
 * persist across a 30s membership refresh or a different authenticated User.
 */
export function reconcileAgentSessionProjectId(
  previous: string|null,
  projects: readonly {id:string;permissions:readonly string[]}[],
):string|null {
  if(previous!==null&&projects.some(project=>project.id===previous&&
    (project.permissions.includes("use_resources")||
      project.permissions.includes("approve_agent_session"))))return previous
  return preferredAgentSessionProjectId(projects)
}
