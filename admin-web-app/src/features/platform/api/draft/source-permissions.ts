/** Verified A5 source decisions, mapped as presentation hints; backend always reauthorizes. */
import { DraftContractError } from "@/features/platform/api/draft/source-contract"
import type {
  DraftMeContext, DraftProjectActions, DraftTeamActions,
} from "@/features/platform/api/draft/source-overview"
import type { UiCapability } from "@/features/platform/model/contracts"

export type SourceUiActions = Partial<Record<UiCapability, boolean>>

/** These operations have current authenticated principal checks in A5. */
export function accountActions(current: DraftMeContext): SourceUiActions {
  if (!current.user.enabled) return {}
  return {
    "profile.read":true,
    "profile.password":current.user.allowed_actions.includes("identity.password.change"),
    "invitations.issue":true, "invitations.revoke":true,
    "teams.read":true, "teams.create":true,
    "projects.read":true, "projects.create":true,
  }
}
export function operatorActions(current: DraftMeContext): SourceUiActions {
  if (!current.user.enabled || !current.global_operator || current.user.role !== "superuser" ||
      !current.user.allowed_actions.includes("identity.users.list")) return {}
  return {
    ...accountActions(current),
    "users.read":true, "users.manage":true, "users.resetPassword":true, "users.roles":true,
    "teams.members":true, "teams.ownership":true,
    "projects.transfer":true,
  }
}
export function teamActions(value: DraftTeamActions): SourceUiActions {
  return {
    "teams.read":true,
    "teams.members":value.can_manage_members,
    "teams.ownership":value.can_transfer_team,
    "accounts.read":true,
    "variables.read":true,
    "accounts.teamManage":value.can_manage_resources,
    "variables.teamManage":value.can_manage_resources,
  }
}
export function projectActions(value: DraftProjectActions): SourceUiActions {
  const canUse = value.permissions.includes("use_resources")
  const permitted = value.can_manage_project_resources
  const teamPermitted = value.can_manage_team_resources && value.owner_scope==="team"
  return {
    "projects.read":true, "projects.transfer":value.can_transfer_project,
    "agents.read":true, "agents.manage":value.can_manage_agents,
    "sessions.read":true, "sessions.open":true, "sessions.request":true,
    "sessions.resolve":value.can_approve_agent_sessions,
    "sessions.revoke":true,
    // A5 accepted read-only /projects/{id}/operational-state is guarded by
    // project_permit; this does NOT grant operational commands or process IO.
    "operations.metadata.read":true,
    "accounts.read":canUse, "variables.read":canUse,
    "accounts.manage":permitted, "variables.manage":permitted,
    "accounts.teamManage":teamPermitted, "variables.teamManage":teamPermitted,
    "teams.members":value.can_manage_team_members,
  }
}

/** A4 ProjectActions.owner_scope is 'project' for personal, with owner_id=Project ID. */
export function validateOwnerDecision(
  project: {project_id:string;owner_user_id:string|null;owner_team_id:string|null},
  permit: DraftProjectActions,
): void {
  if (project.project_id!==permit.project_id) throw new DraftContractError("project_action_scope_mismatch")
  if (project.owner_team_id) {
    if (permit.owner_scope!=="team" || permit.owner_id!==project.owner_team_id)
      throw new DraftContractError("project_team_owner_decision_mismatch")
  } else if (project.owner_user_id) {
    if (permit.owner_scope!=="project" || permit.owner_id!==project.project_id)
      throw new DraftContractError("project_personal_owner_decision_mismatch")
  } else throw new DraftContractError("project_owner_xor_invalid")
}

export function requireDecisionMatch(actual:string|null, permit:string, kind:"team"|"project"): void {
  if (!actual || actual!==permit) throw new DraftContractError(`${kind}_access_revision_mismatch`)
}
