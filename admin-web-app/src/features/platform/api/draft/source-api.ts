/** Private development consumer for ACTUAL unmounted Python router declarations. */
import {
  parseDraftMeContext, parseDraftTeamActions, parseDraftProjectActions, parseDraftUserDisplay,
  parseDraftInvitationDisplay, parseDraftMemberDisplay, parseDraftSessionDisplay,
  parseDraftApprovalDisplay, parseDraftGrantCatalog, parseDraftOperatorSummary,
  type DraftMeContext, type DraftTeamActions, type DraftProjectActions, type DraftUserDisplay,
  type DraftInvitationDisplay, type DraftMemberDisplay, type DraftSessionDisplay,
  type DraftApprovalDisplay, type DraftGrantCatalog, type DraftOperatorSummary,
} from "@/features/platform/api/draft/source-overview"
import { parseSourceOperationalState, type SourceProjectOperationalState } from "@/features/platform/api/draft/source-state"
import { parseSourceCommandStatus, parseSourceScopedCommandStatus, type SourceScopedCommandStatus, type SourceCommandStatus } from "@/features/platform/api/draft/source-command-status"
import { parseSourceProviderCatalog, type SourceProviderCatalog } from "@/features/platform/api/draft/source-provider-catalog"
import { parseSourcePage, sourcePageQuery, type SourceKeysetPage, A6_PAGE_SIZE } from "@/features/platform/api/draft/source-pages"
import { DraftSourceHttp, type DraftHttpRequest } from "@/features/platform/api/draft/source-http"
import {
  DraftContractError, draftUuid, draftSessionUuid, draftVersion, draftList,
  parseDraftUser, parseDraftTeam, parseDraftMembership, parseDraftProject, parseDraftAgent,
  parseDraftSession, parseDraftPermissions, parseDraftInvitation, parseDraftApproval,
  parseDraftResource, parseDraftRevoked, parseDraftChanged, parseDraftToken, parseDraftLoggedOut,
  type DraftUser, type DraftTeam, type DraftTeamMembership, type DraftProject, type DraftAgent,
  type DraftAgentSession, type DraftPermissionView, type DraftInvitation, type DraftApproval,
  type DraftResource, type DraftResourceRevoked, type DraftAdminToken, type DraftResourceScope,
  type DraftCreateProject, type DraftCreateAgent, type DraftRenameAgent, type DraftSetAgentEnabled, type DraftRegister,
  type DraftChangePassword, type DraftPasswordReset, type DraftCreateIntegration,
  type DraftUpdateIntegration, type DraftRotateIntegration, type DraftCreateVariable,
  type DraftUpdateVariable, type DraftRotateVariable, type DraftTransferProjectOwner,
  type DraftAdminReassignProject, type DraftTransferTeamOwner, type DraftAddMember,
  type DraftRequestElevation, type DraftResolveElevation, type DraftOpenSession,
} from "@/features/platform/api/draft/source-contract"

const project = (id: string) => `/projects/${draftUuid(id)}`
const team = (id: string) => `/teams/${draftUuid(id)}`
const user = (id: string) => `/users/${draftUuid(id)}`
const pathResource = (kind: "integrations" | "variables", id: string) => `/${kind}/${draftUuid(id)}`
const cmd = (key: string, signal?: AbortSignal): DraftHttpRequest => ({ idempotencyKey: key, signal })
const signalOption = (signal?: AbortSignal): DraftHttpRequest => ({ signal })
const must = (condition: unknown, code: string): void => { if (!condition) throw new DraftContractError(code) }
const withScope = (scope: DraftResourceScope = "all"): string => {
  must(["all", "team", "project"].includes(scope), "scope_invalid")
  return `?${new URLSearchParams({scope}).toString()}`
}
const parsedList = <T>(raw: unknown, read: (value: unknown) => T): T[] => draftList(raw, read)

export class DraftPlatformSourceApi {
  readonly http: DraftSourceHttp
  constructor(baseUrl: string) { this.http = new DraftSourceHttp(baseUrl) }

  // A4 platform_auth_api.py: login/logout/refresh with memory-only bearer, no cookies.
  async login(username: string, password: string, signal?: AbortSignal): Promise<Pick<DraftAdminToken, "token_type" | "expires_at">> {
    const raw = await this.http.request("POST", "/auth/login", { username, password }, { signal, public: true })
    const issued = parseDraftToken(raw)
    this.http.adoptIssuedToken(issued)
    return { token_type: issued.token_type, expires_at: issued.expires_at }
  }
  async logout(signal?: AbortSignal): Promise<{ revoked: boolean }> {
    try {
      const response = await this.http.request("POST", "/auth/logout", undefined, { signal })
      return parseDraftLoggedOut(response)
    } finally { this.http.clearCredential() }
  }
  /** A4 auth/refresh rotates the old token; an uncertain refresh must discard it. */
  async refreshToken(signal?:AbortSignal):Promise<Pick<DraftAdminToken,"token_type"|"expires_at">> {
    try {
      const raw=await this.http.request("POST","/auth/refresh",undefined,{signal})
      const next=parseDraftToken(raw)
      this.http.adoptIssuedToken(next)
      return {token_type:next.token_type,expires_at:next.expires_at}
    } catch (cause) {
      this.http.clearCredential()
      throw cause
    }
  }
  get hasToken(): boolean { return this.http.hasVerifiedToken }

  // platform_api.py: read projections.
  async me(signal?: AbortSignal): Promise<DraftUser> {
    return parseDraftUser(await this.http.request("GET", "/me", undefined, signalOption(signal)))
  }
  async teams(signal?: AbortSignal): Promise<DraftTeam[]> {
    return parsedList(await this.http.request("GET", "/teams", undefined, signalOption(signal)), parseDraftTeam)
  }
  async members(teamId: string, signal?: AbortSignal): Promise<DraftTeamMembership[]> {
    return parsedList(await this.http.request("GET", `${team(teamId)}/members`, undefined, signalOption(signal)), parseDraftMembership)
  }
  async projects(signal?: AbortSignal): Promise<DraftProject[]> {
    return parsedList(await this.http.request("GET", "/projects", undefined, signalOption(signal)), parseDraftProject)
  }
  async permissions(projectId: string, signal?: AbortSignal): Promise<DraftPermissionView> {
    const result = parseDraftPermissions(await this.http.request("GET", `${project(projectId)}/permissions`, undefined, signalOption(signal)))
    must(result.project_id === draftUuid(projectId), "project_permission_scope_mismatch")
    return result
  }
  async agents(projectId: string, signal?: AbortSignal): Promise<DraftAgent[]> {
    const result = parsedList(await this.http.request("GET", `${project(projectId)}/agents`, undefined, signalOption(signal)), parseDraftAgent)
    must(result.every(item => item.project_id === draftUuid(projectId)), "agent_scope_mismatch")
    return result
  }

  // platform_overview_api.py — A4-only server computed permissions and lists.
  async context(signal?:AbortSignal):Promise<DraftMeContext> {
    return parseDraftMeContext(await this.http.request("GET","/me/context",undefined,signalOption(signal)))
  }
  async users(signal?:AbortSignal, limit?:number):Promise<DraftUserDisplay[]> {
    if(limit!==undefined&&(!Number.isInteger(limit)||limit<1||limit>250)){
      throw new DraftContractError("source_user_list_limit_invalid")
    }
    const url=limit===undefined?"/users":`/users?limit=${limit}`
    return parsedList(await this.http.request("GET",url,undefined,signalOption(signal)),parseDraftUserDisplay)
  }
  async invitations(signal?:AbortSignal):Promise<DraftInvitationDisplay[]> {
    return parsedList(await this.http.request("GET","/invitations",undefined,signalOption(signal)),parseDraftInvitationDisplay)
  }
  /** Actual A6 bounded UUIDv4 keyset Pages; after cursors never grant access. */
  async userPage(limit=A6_PAGE_SIZE,after?:string|null,signal?:AbortSignal):Promise<SourceKeysetPage<DraftUserDisplay>> {
    return parseSourcePage(await this.http.request("GET",`/users/page${sourcePageQuery(limit,after)}`,undefined,signalOption(signal)),
      parseDraftUserDisplay,item=>item.user_id,limit,after)
  }
  async invitationPage(limit=A6_PAGE_SIZE,after?:string|null,signal?:AbortSignal):Promise<SourceKeysetPage<DraftInvitationDisplay>> {
    return parseSourcePage(await this.http.request("GET",`/invitations/page${sourcePageQuery(limit,after)}`,undefined,signalOption(signal)),
      parseDraftInvitationDisplay,item=>item.invitation_id,limit,after)
  }
  async memberDetailsPage(teamId:string,limit=A6_PAGE_SIZE,after?:string|null,signal?:AbortSignal):Promise<SourceKeysetPage<DraftMemberDisplay>> {
    const id=draftUuid(teamId)
    const page=parseSourcePage(await this.http.request("GET",`${team(id)}/member-details/page${sourcePageQuery(limit,after)}`,undefined,signalOption(signal)),
      parseDraftMemberDisplay,item=>item.user_id,limit,after)
    must(page.items.every(item=>item.team_id===id),"team_member_page_scope_mismatch")
    return page
  }
  async sessionsPage(projectId:string,limit=A6_PAGE_SIZE,after?:string|null,signal?:AbortSignal):Promise<SourceKeysetPage<DraftSessionDisplay>> {
    const id=draftUuid(projectId)
    const page=parseSourcePage(await this.http.request("GET",`${project(id)}/sessions/page${sourcePageQuery(limit,after)}`,undefined,signalOption(signal)),
      parseDraftSessionDisplay,item=>item.session_uuid,limit,after)
    must(page.items.every(item=>item.project_id===id),"project_session_page_scope_mismatch")
    return page
  }
  async approvalsPage(projectId:string,limit=A6_PAGE_SIZE,after?:string|null,signal?:AbortSignal):Promise<SourceKeysetPage<DraftApprovalDisplay>> {
    const id=draftUuid(projectId)
    const page=parseSourcePage(await this.http.request("GET",`${project(id)}/approvals/page${sourcePageQuery(limit,after)}`,undefined,signalOption(signal)),
      parseDraftApprovalDisplay,item=>item.request_id,limit,after)
    must(page.items.every(item=>item.project_id===id),"project_approval_page_scope_mismatch")
    return page
  }
  async teamAccess(teamId:string,signal?:AbortSignal):Promise<DraftTeamActions> {
    const id=draftUuid(teamId)
    const result=parseDraftTeamActions(await this.http.request("GET",`${team(id)}/permissions`,undefined,signalOption(signal)))
    must(result.team_id===id,"team_decision_scope_mismatch")
    return result
  }
  async projectAccess(projectId:string,signal?:AbortSignal):Promise<DraftProjectActions> {
    const id=draftUuid(projectId)
    const result=parseDraftProjectActions(await this.http.request("GET",`${project(id)}/access`,undefined,signalOption(signal)))
    must(result.project_id===id,"project_decision_scope_mismatch")
    return result
  }
  async memberDetails(teamId:string,signal?:AbortSignal):Promise<DraftMemberDisplay[]> {
    const id=draftUuid(teamId)
    const rows=parsedList(await this.http.request("GET",`${team(id)}/member-details`,undefined,signalOption(signal)),parseDraftMemberDisplay)
    must(rows.every(member=>member.team_id===id),"team_member_detail_scope_mismatch")
    return rows
  }
  async sessions(projectId:string,signal?:AbortSignal):Promise<DraftSessionDisplay[]> {
    const id=draftUuid(projectId)
    const rows=parsedList(await this.http.request("GET",`${project(id)}/sessions`,undefined,signalOption(signal)),parseDraftSessionDisplay)
    must(rows.every(session=>session.project_id===id),"project_session_scope_mismatch")
    return rows
  }
  async approvals(projectId:string,signal?:AbortSignal):Promise<DraftApprovalDisplay[]> {
    const id=draftUuid(projectId)
    const rows=parsedList(await this.http.request("GET",`${project(id)}/approvals`,undefined,signalOption(signal)),parseDraftApprovalDisplay)
    must(rows.every(approval=>approval.project_id===id),"project_approval_scope_mismatch")
    return rows
  }
  async grantCatalog(projectId:string,signal?:AbortSignal):Promise<DraftGrantCatalog> {
    return parseDraftGrantCatalog(await this.http.request("GET",`${project(projectId)}/grants-catalog`,undefined,signalOption(signal)))
  }
  async operatorSummary(signal?:AbortSignal):Promise<DraftOperatorSummary> {
    return parseDraftOperatorSummary(await this.http.request("GET","/operator/summary",undefined,signalOption(signal)))
  }

  /** A5 unpublished provider catalog: declares formats, NOT tested connectivity. */
  async providerCatalog(signal?:AbortSignal):Promise<SourceProviderCatalog> {
    return parseSourceProviderCatalog(await this.http.request("GET","/providers/catalog",undefined,signalOption(signal)))
  }
  /** A5 DB-only metadata: every read must bind Project+decision revision. */
  async operationalState(projectId:string,limit=50,signal?:AbortSignal):Promise<SourceProjectOperationalState> {
    const id=draftUuid(projectId)
    if(!Number.isInteger(limit)||limit<1||limit>100)throw new DraftContractError("operational_limit_invalid")
    const result=parseSourceOperationalState(await this.http.request("GET",`${project(id)}/operational-state?limit=${limit}`,undefined,signalOption(signal)))
    must(result.project_id===id,"operational_project_scope_mismatch")
    return result
  }
  /** Status is only Project-scoped; global/Team-scoped keys CANNOT use it. */
  async commandStatus(projectId:string,operation:string,key:string,signal?:AbortSignal):Promise<SourceCommandStatus> {
    const id=draftUuid(projectId)
    if(!/^[A-Za-z][A-Za-z0-9_.:-]{0,127}$/.test(operation))throw new DraftContractError("command_operation_invalid")
    const result=parseSourceCommandStatus(await this.http.request("GET",`${project(id)}/commands/${operation}/status`,undefined,{signal,idempotencyKey:key}))
    must(result.project_id===id&&result.operation===operation,"command_reconciliation_scope_mismatch")
    return result
  }

  /** A6 scopes for Team + resource creation and resource lifecycle. */
  private async scopedCommandStatus(path:string,kind:"team"|"project_resource"|"resource",id:string,operation:string,key:string,signal?:AbortSignal):Promise<SourceScopedCommandStatus> {
    if(!/^[A-Za-z][A-Za-z0-9_.:-]{0,127}$/.test(operation))throw new DraftContractError("source_scoped_operation_invalid")
    const expected=draftUuid(id)
    const result=parseSourceScopedCommandStatus(await this.http.request("GET",path,undefined,{signal,idempotencyKey:key}))
    must(result.scope_kind===kind&&result.scope_id===expected&&result.operation===operation,"source_scoped_command_owner_changed")
    return result
  }
  async teamCommandStatus(teamId:string,operation:string,key:string,signal?:AbortSignal):Promise<SourceScopedCommandStatus> {
    const id=draftUuid(teamId)
    return this.scopedCommandStatus(`${team(id)}/commands/${operation}/status`,"team",id,operation,key,signal)
  }
  async projectResourceCommandStatus(projectId:string,operation:string,key:string,signal?:AbortSignal):Promise<SourceScopedCommandStatus> {
    const id=draftUuid(projectId)
    return this.scopedCommandStatus(`${project(id)}/resource-commands/${operation}/status`,"project_resource",id,operation,key,signal)
  }
  async resourceCommandStatus(resourceId:string,operation:string,key:string,signal?:AbortSignal):Promise<SourceScopedCommandStatus> {
    const id=draftUuid(resourceId)
    return this.scopedCommandStatus(`/resources/${id}/commands/${operation}/status`,"resource",id,operation,key,signal)
  }

  // platform_api.py: Team/Project/Agent commands. All require Idempotency-Key.
  async createTeam(name: string, key: string, signal?: AbortSignal): Promise<DraftTeam> {
    return parseDraftTeam(await this.http.request("POST", "/teams", {name}, cmd(key, signal)))
  }
  async addMember(teamId: string, userId: string, version: number, key: string, signal?: AbortSignal): Promise<DraftTeamMembership> {
    const body: DraftAddMember = {user_id: draftUuid(userId), expected_team_version: draftVersion(version)}
    return parseDraftMembership(await this.http.request("POST", `${team(teamId)}/members`, body, cmd(key, signal)))
  }
  async removeMember(teamId: string, userId: string, version: number, key: string, signal?: AbortSignal): Promise<DraftTeamMembership> {
    return parseDraftMembership(await this.http.request("DELETE", `${team(teamId)}/members/${draftUuid(userId)}`, undefined, {...cmd(key, signal), ifMatchVersion: draftVersion(version)}))
  }
  async transferTeamOwner(teamId: string, userId: string, version: number, key: string, signal?: AbortSignal): Promise<DraftTeam> {
    const body: DraftTransferTeamOwner = {new_owner_user_id: draftUuid(userId), expected_version: draftVersion(version), confirmed:true}
    return parseDraftTeam(await this.http.request("POST", `${team(teamId)}/transfer-owner`, body, cmd(key, signal)))
  }
  async createProject(input: DraftCreateProject, key: string, signal?: AbortSignal): Promise<DraftProject> {
    const body: DraftCreateProject = {name:input.name, owner_team_id:input.owner_team_id ? draftUuid(input.owner_team_id) : null}
    return parseDraftProject(await this.http.request("POST", "/projects", body, cmd(key, signal)))
  }
  async transferProject(projectId: string, input: DraftTransferProjectOwner, key: string, signal?: AbortSignal): Promise<DraftProject> {
    must(Boolean(input.owner_team_id) !== input.withdraw_to_personal, "project_transfer_target_invalid")
    const body: DraftTransferProjectOwner = {...input, expected_version:draftVersion(input.expected_version),owner_team_id:input.owner_team_id?draftUuid(input.owner_team_id):null,confirmed:true}
    return parseDraftProject(await this.http.request("POST", `${project(projectId)}/transfer-owner`, body, cmd(key, signal)))
  }
  async adminReassignProject(projectId: string, input: DraftAdminReassignProject, key: string, signal?: AbortSignal): Promise<DraftProject> {
    must(Boolean(input.new_owner_team_id) !== Boolean(input.new_owner_user_id), "owner_xor_violation")
    const body: DraftAdminReassignProject = {...input,confirmed:true,expected_version:draftVersion(input.expected_version),new_owner_user_id:input.new_owner_user_id?draftUuid(input.new_owner_user_id):null,new_owner_team_id:input.new_owner_team_id?draftUuid(input.new_owner_team_id):null}
    return parseDraftProject(await this.http.request("POST", `${project(projectId)}/admin-reassign`, body, cmd(key, signal)))
  }
  async createAgent(projectId: string, input: DraftCreateAgent, key: string, signal?: AbortSignal): Promise<DraftAgent> {
    const body: DraftCreateAgent = {name:input.name,parent_agent_id:input.parent_agent_id?draftUuid(input.parent_agent_id):null}
    return parseDraftAgent(await this.http.request("POST", `${project(projectId)}/agents`, body, cmd(key, signal)))
  }
  async renameAgent(projectId: string, agentId: string, input: DraftRenameAgent, key: string, signal?: AbortSignal): Promise<DraftAgent> {
    const body: DraftRenameAgent = {name:input.name,expected_version:draftVersion(input.expected_version)}
    return parseDraftAgent(await this.http.request("PATCH", `${project(projectId)}/agents/${draftUuid(agentId)}`, body, cmd(key, signal)))
  }

  async setAgentEnabled(projectId:string,agentId:string,input:DraftSetAgentEnabled,key:string,signal?:AbortSignal):Promise<DraftAgent> {
    const result=parseDraftAgent(await this.http.request("PATCH",`${project(projectId)}/agents/${draftUuid(agentId)}/state`,{
      enabled:input.enabled,expected_version:draftVersion(input.expected_version),confirmed:true,
    },cmd(key,signal)))
    must(result.project_id===draftUuid(projectId)&&result.agent_id===draftUuid(agentId)&&result.enabled===input.enabled,"agent_state_response_mismatch")
    return result
  }

  // platform_api.py: invitation, User and password lifecycle.
  async issueInvitation(key: string, signal?: AbortSignal): Promise<DraftInvitation> {
    return parseDraftInvitation(await this.http.request("POST", "/invitations", undefined, cmd(key, signal)))
  }
  async register(input: DraftRegister, key: string, signal?: AbortSignal): Promise<DraftUser> {
    return parseDraftUser(await this.http.request("POST", "/registration", input, {...cmd(key, signal),public:true}))
  }
  async changePassword(input: DraftChangePassword, key: string, signal?: AbortSignal): Promise<{changed:boolean}> {
    return parseDraftChanged(await this.http.request("POST", "/password/change", input, cmd(key, signal)))
  }
  async resetPassword(input: DraftPasswordReset, key: string, signal?: AbortSignal): Promise<{changed:boolean}> {
    return parseDraftChanged(await this.http.request("POST", "/password/reset", input, {...cmd(key, signal),public:true}))
  }
  async suspend(userId: string, key: string, signal?: AbortSignal): Promise<DraftUser> {
    return parseDraftUser(await this.http.request("POST", `${user(userId)}/suspend`, {confirmed:true}, cmd(key, signal)))
  }
  async restoreUser(userId: string, key: string, signal?: AbortSignal): Promise<DraftUser> {
    return parseDraftUser(await this.http.request("POST", `${user(userId)}/restore`, {confirmed:true}, cmd(key, signal)))
  }
  async setSuperuser(userId: string, enabled: boolean, key: string, signal?: AbortSignal): Promise<DraftUser> {
    return parseDraftUser(await this.http.request("POST", `${user(userId)}/superuser`, {enabled,confirmed:true}, cmd(key, signal)))
  }
  async issuePasswordReset(userId: string, key: string, signal?: AbortSignal): Promise<DraftInvitation> {
    return parseDraftInvitation(await this.http.request("POST", `${user(userId)}/password-reset`, {confirmed:true}, cmd(key, signal)))
  }
  async revokeInvitation(invitationId: string, key: string, signal?: AbortSignal): Promise<{revoked:boolean}> {
    return parseDraftLoggedOut(await this.http.request("DELETE", `/invitations/${draftUuid(invitationId)}`, undefined, cmd(key, signal)))
  }
  async deleteUser(userId: string, key: string, signal?: AbortSignal): Promise<DraftUser> {
    return parseDraftUser(await this.http.request("DELETE", user(userId), {confirmed:true}, cmd(key, signal)))
  }

  // Accepted A5 platform_api.py: normal Session and elevation mutations; A5 overview
  // GET endpoints above provide separately authenticated Session/Approval lists.
  async openNormalSession(projectId: string, input: DraftOpenSession, key: string, signal?: AbortSignal): Promise<DraftAgentSession> {
    return parseDraftSession(await this.http.request("POST", `${project(projectId)}/sessions`, input, cmd(key, signal)))
  }
  async requestElevation(projectId: string, sessionUuid: string, input: DraftRequestElevation, key: string, signal?: AbortSignal): Promise<DraftApproval> {
    must(input.grants.length >= 1 && input.grants.length <= 32 && Number.isInteger(input.seconds) && input.seconds>=1 && input.seconds<=300, "session_elevation_invalid")
    return parseDraftApproval(await this.http.request("POST", `${project(projectId)}/sessions/${draftSessionUuid(sessionUuid)}/elevation`, input, cmd(key, signal)))
  }
  async resolveElevation(projectId: string, approvalId: string, input: DraftResolveElevation, key: string, signal?: AbortSignal): Promise<{session:DraftAgentSession|null}> {
    const body={...input,expected_version:draftVersion(input.expected_version)}
    const raw = await this.http.request("POST", `${project(projectId)}/approvals/${draftUuid(approvalId)}/resolve`, body, cmd(key, signal))
    if (!raw || typeof raw!=="object" || !("session" in raw)) throw new DraftContractError("approval_response_invalid")
    const value=(raw as {session:unknown}).session
    return {session:value===null?null:parseDraftSession(value)}
  }
  async revokeSession(projectId: string, sessionUuid: string, key: string, signal?: AbortSignal): Promise<DraftAgentSession> {
    return parseDraftSession(await this.http.request("POST", `${project(projectId)}/sessions/${draftSessionUuid(sessionUuid)}/revoke`, undefined, cmd(key, signal)))
  }

  // resource_api.py: fully ID-scoped connections, variables and explicit resolution.
  async projectResources(projectId: string, kind: "integrations"|"variables", scope: DraftResourceScope="all", signal?:AbortSignal): Promise<DraftResource[]> {
    const records=parsedList(await this.http.request("GET",`${project(projectId)}/${kind}${withScope(scope)}`,undefined,signalOption(signal)),parseDraftResource)
    must(records.every(item=>item.kind===(kind==="integrations"?"integration":"variable")),"resource_type_mismatch")
    return records
  }
  async teamResources(teamId: string, kind: "integrations"|"variables", signal?:AbortSignal): Promise<DraftResource[]> {
    const records=parsedList(await this.http.request("GET",`${team(teamId)}/${kind}`,undefined,signalOption(signal)),parseDraftResource)
    must(records.every(item=>item.kind===(kind==="integrations"?"integration":"variable") && item.owner_scope==="team" && item.owner_id===draftUuid(teamId)),"resource_team_scope_mismatch")
    return records
  }
  async resolveResource(projectId:string, kind:"integrations"|"variables", selector:{scope:DraftResourceScope; resourceId?:string; name?:string}, signal?:AbortSignal):Promise<DraftResource> {
    must(Boolean(selector.resourceId)!==Boolean(selector.name),"qualified_resource_required")
    const q=new URLSearchParams({scope:selector.scope})
    if(selector.resourceId)q.set("resource_id",draftUuid(selector.resourceId))
    else if(selector.name)q.set("name",selector.name)
    return parseDraftResource(await this.http.request("GET",`${project(projectId)}/${kind}/resolve?${q.toString()}`,undefined,signalOption(signal)))
  }
  async createIntegration(input:DraftCreateIntegration,key:string,signal?:AbortSignal):Promise<DraftResource> {
    draftUuid(input.owner_id)
    return parseDraftResource(await this.http.request("POST","/integrations",input,cmd(key,signal)))
  }
  async updateIntegration(id:string,input:DraftUpdateIntegration,key:string,signal?:AbortSignal):Promise<DraftResource> {
    return parseDraftResource(await this.http.request("PATCH",pathResource("integrations",id),{...input,expected_version:draftVersion(input.expected_version)},cmd(key,signal)))
  }
  async rotateIntegration(id:string,input:DraftRotateIntegration,key:string,signal?:AbortSignal):Promise<DraftResource> {
    return parseDraftResource(await this.http.request("POST",pathResource("integrations",id)+"/rotate",{...input,expected_version:draftVersion(input.expected_version)},cmd(key,signal)))
  }
  async revokeIntegration(id:string,version:number,key:string,signal?:AbortSignal):Promise<DraftResourceRevoked> {
    return parseDraftRevoked(await this.http.request("DELETE",pathResource("integrations",id),undefined,{...cmd(key,signal),ifMatchVersion:draftVersion(version)}))
  }
  async createVariable(input:DraftCreateVariable,key:string,signal?:AbortSignal):Promise<DraftResource> {
    draftUuid(input.owner_id)
    return parseDraftResource(await this.http.request("POST","/variables",input,cmd(key,signal)))
  }
  async updateVariable(id:string,input:DraftUpdateVariable,key:string,signal?:AbortSignal):Promise<DraftResource> {
    return parseDraftResource(await this.http.request("PATCH",pathResource("variables",id),{...input,expected_version:draftVersion(input.expected_version)},cmd(key,signal)))
  }
  async rotateVariable(id:string,input:DraftRotateVariable,key:string,signal?:AbortSignal):Promise<DraftResource> {
    return parseDraftResource(await this.http.request("POST",pathResource("variables",id)+"/rotate",{...input,expected_version:draftVersion(input.expected_version)},cmd(key,signal)))
  }
  async revokeVariable(id:string,version:number,key:string,signal?:AbortSignal):Promise<DraftResourceRevoked> {
    return parseDraftRevoked(await this.http.request("DELETE",pathResource("variables",id),undefined,{...cmd(key,signal),ifMatchVersion:draftVersion(version)}))
  }
}
