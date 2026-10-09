/** SOURCE-ONLY ACCEPTED A5 platform_overview_api.py DTOs. No public router is installed. */
import {
  DraftContractError, draftRecordFields, draftString, draftBoolean, draftInteger,
  draftDate, draftNullable, draftList, draftUuid, draftSessionUuid, draftVersion,draftSourceDefault,
} from "@/features/platform/api/draft/source-contract"

export interface DraftTeamActions {
  team_id: string
  decision_version: string
  can_manage_resources: boolean
  can_manage_members: boolean
  can_transfer_team: boolean
}
export interface DraftProjectActions {
  project_id: string
  owner_scope: "team" | "project"
  owner_id: string
  decision_version: string
  permissions: string[]
  can_manage_project_resources: boolean
  can_approve_agent_sessions: boolean
  can_manage_agents: boolean
  can_transfer_project: boolean
  can_manage_team_members: boolean
  can_manage_team_resources: boolean
}
export interface DraftUserDisplay {
  user_id: string
  username: string
  enabled: boolean
  role: string
  credential_version: number
  allowed_actions: string[]
}
export interface DraftMemberDisplay {
  team_id: string
  user_id: string
  username: string
  enabled: boolean
  active: boolean
}
export interface DraftInvitationDisplay {
  invitation_id: string
  kind: string
  created_at: string
  expires_at: string | null
  used_at: string | null
  revoked_at: string | null
  issuer_id: string | null
  target_user_id: string | null
}
export interface DraftSessionDisplay {
  label: string | null
  session_uuid: string
  project_id: string
  status: "active" | "expired" | "revoked"
  grants: string[]
  is_elevated: boolean
  elevation_policy: "fixed" | "requestable"
  hard_expires_at: string
  created_at: string
  version: number
}
export interface DraftApprovalDisplay {
  version: number
  request_id: string
  session_uuid: string
  project_id: string
  status: "pending" | "approved" | "rejected"
  requested_grants: string[]
  requested_expires_at: string
  issued_session_uuid: string | null
  requested_by_user_id: string
  resolved_by_user_id: string | null
  resolved_at: string | null
}
export interface DraftGrantCatalog {
  normal_hard_ttl_seconds: number
  elevated_max_seconds: number
  basic_grants: string[]
  supported_grants: string[]
}
export interface DraftMeContext {
  user: DraftUserDisplay
  teams: DraftTeamActions[]
  projects: DraftProjectActions[]
  global_operator: boolean
}
export interface DraftOperatorSummary {
  users: number
  teams: number
  projects: number
  agent_sessions: number
}

function decisionVersion(raw: unknown): string {
  const value = draftString(raw)
  // Derived from _platform_permissions._revision(SHA-256) in accepted A4.
  if (!/^[0-9a-f]{64}$/i.test(value)) throw new DraftContractError("decision_revision_invalid")
  return value.toLowerCase()
}
function knownStatus<T extends string>(raw: unknown, values: readonly T[]): T {
  const value = draftString(raw)
  if (!values.some(item=>item===value)) throw new DraftContractError("unknown_source_status")
  return value as T
}
function positiveInt(raw: unknown): number {
  const number = draftInteger(raw)
  if (number <= 0) throw new DraftContractError("nonpositive_source_ttl")
  return number
}
const sourceDate = (raw: unknown) => draftDate(raw)
const sourceUuid = (raw: unknown) => draftUuid(draftString(raw))
const sourceSessionUuid = (raw: unknown) => draftSessionUuid(draftString(raw))

export const parseDraftTeamActions = (raw: unknown): DraftTeamActions => {
  const v = draftRecordFields(raw,['team_id', 'decision_version', 'can_manage_resources', 'can_manage_members', 'can_transfer_team'])
  return {
    team_id:sourceUuid(v.team_id), decision_version:decisionVersion(v.decision_version),
    can_manage_resources:draftBoolean(v.can_manage_resources),
    can_manage_members:draftBoolean(v.can_manage_members),
    can_transfer_team:draftBoolean(v.can_transfer_team),
  }
}
export const parseDraftProjectActions = (raw: unknown): DraftProjectActions => {
  const v = draftRecordFields(raw,['project_id', 'owner_scope', 'owner_id', 'decision_version', 'permissions', 'can_manage_project_resources', 'can_approve_agent_sessions', 'can_manage_agents', 'can_transfer_project', 'can_manage_team_members', 'can_manage_team_resources'])
  const owner_scope = knownStatus(v.owner_scope,["team","project"] as const)
  const permissions = draftList(v.permissions,draftString)
  // Unknown codes may be recorded as metadata, but NEVER mapped to UI rights.
  return {
    project_id:sourceUuid(v.project_id), owner_scope, owner_id:sourceUuid(v.owner_id),
    decision_version:decisionVersion(v.decision_version), permissions,
    can_manage_project_resources:draftBoolean(v.can_manage_project_resources),
    can_approve_agent_sessions:draftBoolean(v.can_approve_agent_sessions),
    can_manage_agents:draftBoolean(v.can_manage_agents),
    can_transfer_project:draftBoolean(v.can_transfer_project),
    can_manage_team_members:draftBoolean(v.can_manage_team_members),
    can_manage_team_resources:draftBoolean(v.can_manage_team_resources),
  }
}
export const parseDraftUserDisplay = (raw: unknown): DraftUserDisplay => {
  const v = draftRecordFields(raw,['user_id', 'username', 'enabled', 'role', 'credential_version', 'allowed_actions'])
  const role = knownStatus(v.role,["user","superuser"] as const)
  return {user_id:sourceUuid(v.user_id),username:draftString(v.username),enabled:draftBoolean(v.enabled),role,credential_version:draftVersion(draftInteger(v.credential_version)),
    allowed_actions:draftSourceDefault(v.allowed_actions,[] as string[],raw=>draftList(raw,draftString))}
}
export const parseDraftMemberDisplay = (raw: unknown): DraftMemberDisplay => {
  const v = draftRecordFields(raw,['team_id', 'user_id', 'username', 'enabled', 'active'])
  return {team_id:sourceUuid(v.team_id),user_id:sourceUuid(v.user_id),username:draftString(v.username),enabled:draftBoolean(v.enabled),active:draftBoolean(v.active)}
}
export const parseDraftInvitationDisplay = (raw: unknown): DraftInvitationDisplay => {
  const v = draftRecordFields(raw,['invitation_id', 'kind', 'created_at', 'expires_at', 'used_at', 'revoked_at', 'issuer_id', 'target_user_id'])
  return {
    invitation_id:sourceUuid(v.invitation_id),kind:draftString(v.kind),created_at:sourceDate(v.created_at),
    expires_at:draftNullable(v.expires_at,sourceDate),used_at:draftNullable(v.used_at,sourceDate),
    revoked_at:draftNullable(v.revoked_at,sourceDate),issuer_id:draftNullable(v.issuer_id,sourceUuid),
    target_user_id:draftNullable(v.target_user_id,sourceUuid),
  }
}
export const parseDraftSessionDisplay = (raw: unknown): DraftSessionDisplay => {
  const v=draftRecordFields(raw,['label', 'session_uuid', 'project_id', 'status', 'grants', 'is_elevated', 'elevation_policy', 'hard_expires_at', 'created_at', 'version'])
  return {
    // A5 SessionDisplay.label is required but explicitly nullable.
    label:draftNullable(v.label,draftString),
    session_uuid:sourceSessionUuid(v.session_uuid),project_id:sourceUuid(v.project_id),
    status:knownStatus(v.status,["active","expired","revoked"] as const),
    grants:draftList(v.grants,draftString),is_elevated:draftBoolean(v.is_elevated),
    elevation_policy:knownStatus(v.elevation_policy,["fixed","requestable"] as const),
    hard_expires_at:sourceDate(v.hard_expires_at),created_at:sourceDate(v.created_at),
    version:draftVersion(draftInteger(v.version)),
  }
}
export const parseDraftApprovalDisplay = (raw: unknown): DraftApprovalDisplay => {
  const v=draftRecordFields(raw,['version', 'request_id', 'session_uuid', 'project_id', 'status', 'requested_grants', 'requested_expires_at', 'issued_session_uuid', 'requested_by_user_id', 'resolved_by_user_id', 'resolved_at'])
  return {
    version:draftVersion(draftInteger(v.version)),request_id:sourceUuid(v.request_id),
    session_uuid:sourceSessionUuid(v.session_uuid),project_id:sourceUuid(v.project_id),
    status:knownStatus(v.status,["pending","approved","rejected"] as const),
    requested_grants:draftList(v.requested_grants,draftString),
    requested_expires_at:sourceDate(v.requested_expires_at),
    issued_session_uuid:draftNullable(v.issued_session_uuid,sourceSessionUuid),
    requested_by_user_id:sourceUuid(v.requested_by_user_id),
    resolved_by_user_id:draftNullable(v.resolved_by_user_id,sourceUuid),
    resolved_at:draftNullable(v.resolved_at,sourceDate),
  }
}
export const parseDraftGrantCatalog = (raw: unknown): DraftGrantCatalog => {
  const v=draftRecordFields(raw,['normal_hard_ttl_seconds', 'elevated_max_seconds', 'basic_grants', 'supported_grants'])
  const basic_grants=draftList(v.basic_grants,draftString)
  const supported_grants=draftList(v.supported_grants,draftString)
  if (new Set(supported_grants).size!==supported_grants.length ||
      new Set(basic_grants).size!==basic_grants.length ||
      basic_grants.some(item=>!supported_grants.includes(item))) throw new DraftContractError("grant_catalog_inconsistent")
  return {
    normal_hard_ttl_seconds:positiveInt(v.normal_hard_ttl_seconds),
    elevated_max_seconds:positiveInt(v.elevated_max_seconds),
    basic_grants,supported_grants,
  }
}
export const parseDraftMeContext = (raw: unknown): DraftMeContext => {
  const v=draftRecordFields(raw,['user', 'teams', 'projects', 'global_operator'])
  const user=parseDraftUserDisplay(v.user)
  const teams=draftList(v.teams,parseDraftTeamActions)
  const projects=draftList(v.projects,parseDraftProjectActions)
  if (new Set(teams.map(item=>item.team_id)).size!==teams.length ||
      new Set(projects.map(item=>item.project_id)).size!==projects.length ||
      draftBoolean(v.global_operator)!==(user.role==="superuser")) {
    throw new DraftContractError("identity_projection_inconsistent")
  }
  return {user,teams,projects,global_operator:draftBoolean(v.global_operator)}
}
export const parseDraftOperatorSummary = (raw: unknown): DraftOperatorSummary => {
  const v=draftRecordFields(raw,['users', 'teams', 'projects', 'agent_sessions'])
  const users=draftInteger(v.users),teams=draftInteger(v.teams),projects=draftInteger(v.projects),agent_sessions=draftInteger(v.agent_sessions)
  if ([users,teams,projects,agent_sessions].some(value=>value<0)) throw new DraftContractError("negative_operator_count")
  return {users,teams,projects,agent_sessions}
}
