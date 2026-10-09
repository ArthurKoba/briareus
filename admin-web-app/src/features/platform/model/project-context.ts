import { reactive, readonly } from "vue"
import { commandCoordinator } from "@/features/platform/model/command-coordinator"
import type { AccessProjection, UiCapability, ScopeSelection } from "@/features/platform/model/contracts"

/** These are UI projections, not wire DTOs or permission decisions. */
export interface AuthenticatedUserContext {
  key: string
  label: string
  active: boolean
  isSuperuser: boolean
}
export type ProjectOwnership = "personal" | "team"
export interface AvailableProjectContext {
  key: string
  label: string
  ownership: ProjectOwnership
  ownerLabel?: string
  ownerTeamId?: string
}
export interface AvailableTeamContext { key: string; label: string }
export interface ResolvedUserProjects {
  user: AuthenticatedUserContext
  projects: AvailableProjectContext[]
  teams?: AvailableTeamContext[]
  permissions?: Partial<Record<UiCapability, boolean>>
  projectPermissions?: Record<string, Partial<Record<UiCapability, boolean>>>
  teamPermissions?: Record<string, Partial<Record<UiCapability, boolean>>>
  operatorPermissions?: Partial<Record<UiCapability, boolean>>
  projectDecisionVersions?: Record<string, string>
  teamDecisionVersions?: Record<string, string>
}
export type ShellScope = "signed-out" | "legacy" | "choose-project" | "project" | "team" | "operator" | "suspended" | "offline"

const state = reactive({
  scope: "signed-out" as ShellScope,
  user: null as AuthenticatedUserContext | null,
  projects: [] as AvailableProjectContext[],
  teams: [] as AvailableTeamContext[],
  permissions: {} as Partial<Record<UiCapability, boolean>>,
  projectPermissions: {} as Record<string, Partial<Record<UiCapability, boolean>>>,
  teamPermissions: {} as Record<string, Partial<Record<UiCapability, boolean>>>,
  operatorPermissions: {} as Partial<Record<UiCapability, boolean>>,
  projectDecisionVersions: {} as Record<string,string>,
  teamDecisionVersions: {} as Record<string,string>,
  activeProjectKey: null as string | null,
  activeTeamKey: null as string | null,
  revision: 0,
})
const transitionListeners = new Set<() => void>()
let lastVerifiedSnapshot: string | null = null

/** Stable comparison without exposing credentials or interpreting unknown grants. */
function verifiedSnapshot(context: ResolvedUserProjects): string {
  const sortedMap = (input?: Record<string, unknown>) =>
    Object.entries(input ?? {}).sort(([a],[b])=>a.localeCompare(b)).map(([key,value])=>{
      if (value && typeof value==="object" && !Array.isArray(value)) {
        return [key, Object.entries(value).sort(([a],[b])=>a.localeCompare(b))]
      }
      return [key,value]
    })
  return JSON.stringify({
    user:context.user,
    teams:[...(context.teams??[])].sort((a,b)=>a.key.localeCompare(b.key)),
    projects:[...context.projects].sort((a,b)=>a.key.localeCompare(b.key)),
    permissions:sortedMap(context.permissions),
    projectPermissions:sortedMap(context.projectPermissions),
    teamPermissions:sortedMap(context.teamPermissions),
    operatorPermissions:sortedMap(context.operatorPermissions),
    projectDecisionVersions:sortedMap(context.projectDecisionVersions),
    teamDecisionVersions:sortedMap(context.teamDecisionVersions),
  })
}

function transition(scope: ShellScope, project: string | null = null, team: string | null = null): void {
  state.scope = scope
  state.activeProjectKey = project
  state.activeTeamKey = team
  ++state.revision
  // All requests, caches, subscriptions and old views must be invalidated here.
  for (const listener of transitionListeners) listener()
}
function resetIdentity(): void {
  lastVerifiedSnapshot = null
  commandCoordinator.clearAll()
  state.user = null
  state.projects = []
  state.teams = []
  state.permissions = {}
  state.projectPermissions = {}
  state.teamPermissions = {}
  state.operatorPermissions = {}
  state.projectDecisionVersions = {}
  state.teamDecisionVersions = {}
}
function beginLegacySession(): void {
  resetIdentity()
  transition("legacy")
}
function clear(): void {
  resetIdentity()
  transition("signed-out")
}
function offline(): void {
  resetIdentity()
  transition("offline")
}
function suspend(): void {
  lastVerifiedSnapshot = null
  state.projects = []
  state.teams = []
  state.permissions = {}
  state.projectPermissions = {}
  state.teamPermissions = {}
  state.operatorPermissions = {}
  state.projectDecisionVersions = {}
  state.teamDecisionVersions = {}
  transition("suspended")
}

function installResolvedContext(context: ResolvedUserProjects): void {
  if (!context.user.active) {
    state.user = { ...context.user }
    suspend()
    return
  }
  const signature = verifiedSnapshot(context)
  if (lastVerifiedSnapshot === signature && state.user?.key === context.user.key &&
      ["choose-project","project","team","operator"].includes(state.scope)) return
  const previousUser=state.user?.key
  const previousScope=state.scope
  const previousProject=state.activeProjectKey
  const previousTeam=state.activeTeamKey
  state.user = { ...context.user }
  state.projects = context.projects.map(project => ({ ...project }))
  state.teams = (context.teams ?? []).map(team => ({ ...team }))
  state.permissions = { ...context.permissions }
  state.projectPermissions = Object.fromEntries(
    context.projects.map(project => [project.key, { ...context.projectPermissions?.[project.key] }]),
  )
  state.teamPermissions = Object.fromEntries(
    state.teams.map(team => [team.key, { ...context.teamPermissions?.[team.key] }]),
  )
  state.operatorPermissions = context.user.isSuperuser ? { ...context.operatorPermissions } : {}
  state.projectDecisionVersions = {...context.projectDecisionVersions}
  state.teamDecisionVersions = {...context.teamDecisionVersions}
  lastVerifiedSnapshot=signature

  // Exactly ONE invalidation for a changed server grant/owner/principal.
  // Keep the explicit selection if the SAME authenticated User still sees
  // that entity; a Team-owner transfer changes scope rights, not its ID.
  if (previousUser === context.user.key) {
    if (previousScope === "project" && previousProject && context.projects.some(project => project.key === previousProject)) {
      transition("project", previousProject)
      return
    }
    if (previousScope === "team" && previousTeam && context.teams?.some(team => team.key === previousTeam)) {
      transition("team", null, previousTeam)
      return
    }
    if (previousScope === "operator" && context.user.isSuperuser) {
      transition("operator")
      return
    }
  }
  transition("choose-project")
}

/** Adapter may only call this with a server-authenticated projection (no fake fallback). */
function installServerProjection(projection: AccessProjection): void {
  if (state.user && state.user.key !== projection.user.userId) commandCoordinator.clearAll()
  const next: ResolvedUserProjects = {
    user: {
      key: projection.user.userId,
      label: projection.user.displayName || projection.user.username,
      active: projection.user.active,
      isSuperuser: projection.user.isSuperuser,
    },
    teams: projection.teams?.map(team => ({key:team.teamId,label:team.name})),
    projects: projection.projects.map(project => ({
      key: project.projectId,
      label: project.name,
      ownership: project.owner.kind === "user" ? "personal" : "team",
      ownerLabel: project.owner.kind === "team" ? project.owner.teamName : undefined,
      ownerTeamId: project.owner.kind === "team" ? project.owner.teamId : undefined,
    })),
    permissions: projection.permissions,
    projectPermissions: projection.projectPermissions,
    teamPermissions: projection.teamPermissions,
    operatorPermissions: projection.operatorPermissions,
    projectDecisionVersions: projection.projectDecisionVersions,
    teamDecisionVersions: projection.teamDecisionVersions,
  }
  installResolvedContext(next)
}

function selectProject(key: string): boolean {
  if (!state.user?.active || !state.projects.some(project => project.key === key)) return false
  if (state.scope !== "project" || state.activeProjectKey !== key) transition("project", key)
  return true
}
function selectTeam(key: string): boolean {
  if (!state.user?.active || !state.teams.some(team => team.key === key)) return false
  if (state.scope !== "team" || state.activeTeamKey !== key) transition("team", null, key)
  return true
}
function selectOperator(): boolean {
  if (!state.user?.active || !state.user.isSuperuser) return false
  if (state.scope !== "operator") transition("operator")
  return true
}
function selectNone(): void {
  if (state.user?.active) transition("choose-project")
}
function selection(): ScopeSelection | null {
  if (state.scope === "choose-project" && state.user?.active) return { kind: "account" }
  if (state.scope === "project" && state.activeProjectKey) return { kind: "project", projectId: state.activeProjectKey }
  if (state.scope === "team" && state.activeTeamKey) return { kind: "team", teamId: state.activeTeamKey }
  if (state.scope === "operator" && state.user?.isSuperuser) return { kind: "operator" }
  return null
}
function can(action: UiCapability): boolean {
  if (!state.user?.active) return false
  // These are PERSON-scoped actions, not Project/Team grants. They remain
  // accessible while a verified User has selected a Team or Project.
  if (["profile.read", "profile.password", "invitations.issue", "invitations.revoke",
       "teams.read", "teams.create", "projects.read", "projects.create"].includes(action)) {
    return state.permissions[action] === true
  }
  if (state.scope === "choose-project") return state.permissions[action] === true
  if (state.scope === "project" && state.activeProjectKey) return state.projectPermissions[state.activeProjectKey]?.[action] === true
  if (state.scope === "team" && state.activeTeamKey) return state.teamPermissions[state.activeTeamKey]?.[action] === true
  if (state.scope === "operator" && state.user.isSuperuser) return state.operatorPermissions[action] === true
  return false
}
function onTransition(listener: () => void): () => void {
  transitionListeners.add(listener)
  return () => { transitionListeners.delete(listener) }
}

/** The server must independently authorize EVERY protected call and event. */
export const projectContext = {
  state: readonly(state),
  beginLegacySession, clear, offline, suspend,
  installServerProjection,
  selectProject, selectTeam, selectOperator, selectNone,
  selection, can, onTransition,
}
