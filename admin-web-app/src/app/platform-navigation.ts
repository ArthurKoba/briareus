import type { UiCapability } from "@/features/platform/model/contracts"
import { projectContext } from "@/features/platform/model/project-context"

/** Pure UI routing intent; the adapter maps effective server grants to these hints. */
export type PlatformPageId = "home" | "users" | "teams" | "projects" | "agents" | "sessions" | "integrations" | "variables" | "dashboard" | "calls" | "oauth" | "files" | "terminal" | "browser-managed" | "browser-external" | "analysis" | "settings"
export interface PlatformNavigationItem {
  id: PlatformPageId
  title: string
  section: "work" | "resources" | "console"
  permissions: UiCapability[]
  scope: "any" | "project" | "teamOrProject" | "global"
}
export const platformNavigation: readonly PlatformNavigationItem[] = [
  { id:"home",title:"home",section:"work",permissions:[],scope:"any" },
  { id:"users",title:"users",section:"work",permissions:["profile.read","profile.password","invitations.issue","users.read"],scope:"any" },
  { id:"teams",title:"teams",section:"work",permissions:["teams.read","teams.create"],scope:"any" },
  { id:"projects",title:"projects",section:"work",permissions:["projects.read","projects.create"],scope:"any" },
  { id:"agents",title:"agents",section:"work",permissions:["agents.read","agents.manage"],scope:"project" },
  { id:"sessions",title:"sessions",section:"work",permissions:["sessions.read","sessions.resolve"],scope:"project" },
  { id:"integrations",title:"integrations",section:"resources",permissions:["accounts.read","accounts.manage","accounts.teamManage"],scope:"teamOrProject" },
  { id:"variables",title:"variables",section:"resources",permissions:["variables.read","variables.manage","variables.teamManage"],scope:"teamOrProject" },
  { id:"dashboard",title:"dashboard",section:"resources",permissions:["dashboard.read"],scope:"project" },
  { id:"calls",title:"calls",section:"resources",permissions:["calls.read"],scope:"project" },
  { id:"oauth",title:"oauth",section:"resources",permissions:["oauth.read"],scope:"project" },
  { id:"files",title:"files",section:"resources",permissions:["files.read"],scope:"project" },
  { id:"terminal",title:"terminal",section:"resources",permissions:["terminal.read"],scope:"project" },
  { id:"browser-managed",title:"browserManaged",section:"resources",permissions:["browser.managed.read"],scope:"project" },
  { id:"browser-external",title:"browserExternal",section:"resources",permissions:["browser.external.read"],scope:"project" },
  { id:"analysis",title:"analysis",section:"resources",permissions:["analysis.read"],scope:"project" },
  { id:"settings",title:"settings",section:"console",permissions:[],scope:"any" },
] as const

/** A4 has no Project operational REST APIs; these are informational,
 * denied-by-default source read views rather than working MCP controls. */
const operationalPreviewPages = new Set<PlatformPageId>([
  "dashboard","calls","oauth","files","terminal","browser-managed",
  "browser-external","analysis",
])
export function visiblePlatformPages(preview=false): PlatformNavigationItem[] {
  if (preview) return [...platformNavigation]
  const scope=projectContext.state.scope
  return platformNavigation.filter(item => {
    if (item.scope==="project" && scope!=="project") return false
    // Selected, authenticated Project users may open a *blocked* information
    // screen even before C2 exists. It reveals NO records without a verified
    // server-issued permission and an installed scoped read adapter.
    if (item.scope==="project" && operationalPreviewPages.has(item.id)) return true
    if (item.scope==="teamOrProject" && scope!=="project" && scope!=="team") return false
    if (item.scope==="global" && scope!=="operator") return false
    if (item.scope==="any") return true
    return item.permissions.some(permission=>projectContext.can(permission))
  })
}
export function validPlatformPage(id:string, preview=false):id is PlatformPageId {
  return visiblePlatformPages(preview).some(item=>item.id===id)
}
