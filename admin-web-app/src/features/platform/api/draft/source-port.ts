/**
 * Uninstalled consumer adapter for the current unmounted Backend draft.
 * SOURCE/API parity is distinct from C1-B2 approval and live authentication.
 * No import from main.ts, no automatic installation and NO fallback to legacy API.
 */
import {
  draftUuid, draftVersion, missingContract, DraftContractError,
  type DraftProject, type DraftTeam, type DraftAgent, type DraftResource,
} from "@/features/platform/api/draft/source-contract"
import { DraftPlatformSourceApi } from "@/features/platform/api/draft/source-api"
import type { SourceProjectOperationalState } from "@/features/platform/api/draft/source-state"
import {
  type DraftMeContext, type DraftProjectActions,
  type DraftUserDisplay, type DraftSessionDisplay, type DraftApprovalDisplay,
} from "@/features/platform/api/draft/source-overview"
import {
  accountActions, operatorActions, projectActions, teamActions, validateOwnerDecision,
  requireDecisionMatch,
} from "@/features/platform/api/draft/source-permissions"
import type {
  AccessProjection, AgentView, AgentSessionView, AvailableProject, AvailableTeamScope,
  CommandContext, MutationResult, PlatformPort, ProjectAccountInput, ProjectAccountView,
  ProjectVariableInput, ProjectVariableView, ProjectView, QueryContext, ResourceOwner,
  ResourceVisibility, ScopeSelection, TeamView, UserView, AgentSessionRequestView,OperationalArea,OperationalItemView,
} from "@/features/platform/model/contracts"
import { canonicalUuid4 } from "@/features/platform/model/contracts"

function requireSourceDecision(ctx:QueryContext, actual:string):void {
  if((ctx.scope.kind==="project"||ctx.scope.kind==="team")&&
     (!ctx.decisionVersion||ctx.decisionVersion!==actual)) {
    throw new DraftContractError("verified_permission_revision_changed")
  }
}
function scopeProject(ctx: QueryContext): string {
  if (ctx.scope.kind !== "project") return missingContract("project_selection_required")
  return draftUuid(ctx.scope.projectId)
}
function scopeResource(ctx: QueryContext): string {
  if (ctx.scope.kind !== "project" && ctx.scope.kind !== "team") return missingContract("resource_owner_selection_required")
  return draftUuid(ctx.scope.kind === "project" ? ctx.scope.projectId : ctx.scope.teamId)
}
function ownerToDraft(owner: ResourceOwner): { owner_scope: "team" | "project"; owner_id: string } {
  return {owner_scope: owner.kind, owner_id: draftUuid(owner.kind === "team" ? owner.teamId : owner.projectId)}
}
function visibility(scope: ScopeSelection): ResourceVisibility {
  if (scope.kind === "project") return {kind:"project",projectId:draftUuid(scope.projectId)}
  if (scope.kind === "team") return {kind:"team",teamId:draftUuid(scope.teamId)}
  return missingContract("resource_visibility_missing")
}
function projectOwner(value: DraftProject, teams: ReadonlyMap<string, DraftTeam>): AvailableProject["owner"] {
  if (value.owner_user_id) return {kind:"user",userId:value.owner_user_id}
  if (value.owner_team_id) {
    const team = teams.get(value.owner_team_id)
    // Never synthesize an unknown Team label or imply visible membership.
    if (!team) return missingContract("team_owner_projection_missing")
    return {kind:"team",teamId:value.owner_team_id,teamName:team.name}
  }
  return missingContract("project_owner_missing")
}
const mapProject = (
  item: DraftProject, teams: ReadonlyMap<string, DraftTeam>, permit?: DraftProjectActions,
): ProjectView => {
  if (permit) validateOwnerDecision(item,permit)
  return {
    projectId:item.project_id,name:item.name,owner:projectOwner(item,teams),revision:String(item.version),
    ...(permit?{decisionVersion:permit.decision_version,allowedActions:projectActions(permit)}:{}),
  }
}
const mapUser = (dto: DraftUserDisplay, ownedTeams?:number, ownedProjects?:number, current?:DraftMeContext): UserView => {
  const sourceActions=new Set(dto.allowed_actions)
  const isOperator=Boolean(current?.global_operator && current.user.allowed_actions.includes("identity.users.list"))
  return {
    id:dto.user_id,username:dto.username,displayName:dto.username,active:dto.enabled,isSuperuser:dto.role==="superuser",
    ...(ownedTeams!==undefined?{ownsTeams:ownedTeams}:{}),
    ...(ownedProjects!==undefined?{ownsPersonalProjects:ownedProjects}:{}),
    sourceActions:[...dto.allowed_actions],
    allowedActions:{
      "users.read":isOperator,
      "users.manage":isOperator && ["identity.suspend","identity.restore","identity.delete"].some(code=>sourceActions.has(code)),
      "users.roles":isOperator && ["identity.superuser.demote","identity.superuser.promote"].some(code=>sourceActions.has(code)),
      "users.resetPassword":isOperator && sourceActions.has("identity.password_reset.issue"),
    },
    // User credential_version is NOT a User record expected_version.
  }
}
const mapAgent = (dto: DraftAgent): AgentView => ({
  id:dto.agent_id,projectId:dto.project_id,label:dto.name,parentAgentId:dto.parent_agent_id,
  status:dto.enabled?"active":"disabled",revision:String(dto.version),
})
function mapSession(
  dto: {session_uuid:string;project_id:string;grants:string[];is_elevated:boolean;hard_expires_at:string;status:string;version:number},
  permit?:DraftProjectActions,
): AgentSessionView {
  if (!canonicalUuid4(dto.session_uuid)) return missingContract("session_uuid_invalid")
  if (!["active","revoked","expired","pending"].includes(dto.status)) return missingContract("session_status_unrecognized")
  const active=dto.status==="active"&&Date.parse(dto.hard_expires_at)>Date.now()
  const policy="elevation_policy" in dto ? dto.elevation_policy : null
  if (policy!==null && policy!=="fixed" && policy!=="requestable") return missingContract("session_policy_invalid")
  return {
    sessionUuid:dto.session_uuid,projectId:dto.project_id,
    label:"label" in dto && typeof dto.label==="string" && dto.label.trim()?dto.label:dto.session_uuid,
    status:active?"active":dto.status==="active"?"expired":dto.status as AgentSessionView["status"],
    elevation:dto.is_elevated?"elevated":"normal",elevationPolicy:policy,
    expiresAt:dto.hard_expires_at,grants:[...dto.grants],revision:String(dto.version),
    ...("created_at" in dto && typeof dto.created_at==="string"?{createdAt:dto.created_at}:{}),
    ...(permit?{allowedActions:{
      "sessions.revoke":active,"sessions.request":active&&!dto.is_elevated&&policy==="requestable",
    }}:{}),
  }
}
/** Local comparison key from actual A4 fields, never a fabricated server revision. */
function approvalSnapshot(dto:DraftApprovalDisplay):string {
  return JSON.stringify([
    dto.version,dto.request_id,dto.session_uuid,dto.project_id,dto.status,dto.requested_grants,
    dto.requested_expires_at,dto.issued_session_uuid,dto.requested_by_user_id,
    dto.resolved_by_user_id,dto.resolved_at,
  ])
}
function mapApproval(
  dto:DraftApprovalDisplay,permit:DraftProjectActions,sessions:readonly DraftSessionDisplay[],
):AgentSessionRequestView {
  const base=sessions.find(item=>item.session_uuid===dto.session_uuid)
  const now=Date.now()
  const safe=Boolean(base&&base.status==="active"&&Date.parse(base.hard_expires_at)>now)
  const blockReason=dto.status!=="pending"?undefined:
    !base?"missing-base-session" as const:
    !safe?"inactive-base-session" as const:
    Date.parse(dto.requested_expires_at)<=now?"expired-request" as const:
    !permit.can_approve_agent_sessions?"missing-approval-rights" as const:undefined
  return {
    id:dto.request_id,sessionUuid:dto.session_uuid,projectId:dto.project_id,
    revision:String(dto.version),
    requestedBy:dto.requested_by_user_id,status:dto.status,
    requestedGrants:[...dto.requested_grants],requestedUntil:dto.requested_expires_at,
    snapshotKey:approvalSnapshot(dto),
    ...(blockReason?{blockReason}:{}),
    allowedActions:{"sessions.resolve":!blockReason&&dto.status==="pending"},
  }
}
const knownProvider = ["github","gitlab","signoz","coolify","grafana","zoomies"] as const
function mapResourceOwner(dto: DraftResource): ResourceOwner {
  return dto.owner_scope==="team"?{kind:"team",teamId:dto.owner_id}:{kind:"project",projectId:dto.owner_id}
}
function validateResourceScope(dto: DraftResource, ctx: QueryContext, expectedKind: "integration"|"variable"): void {
  if (dto.kind!==expectedKind || dto.owner_scope!==dto.origin) return missingContract("resource_kind_or_origin_invalid")
  if (ctx.scope.kind==="team") {
    if (dto.owner_scope!=="team" || dto.owner_id!==ctx.scope.teamId || dto.inherited) return missingContract("team_resource_scope_invalid")
  } else if (ctx.scope.kind==="project") {
    if (dto.owner_scope==="project" && (dto.owner_id!==ctx.scope.projectId || dto.inherited)) return missingContract("project_resource_scope_invalid")
    // Team ownership/inheritance is verified by backend and also by the UI's
    // current server-resolved Project owner Team ID (see ProjectAccountsPage).
    if (dto.owner_scope==="team" && !dto.inherited) return missingContract("inherited_resource_provenance_invalid")
  } else return missingContract("resource_scope_invalid")
}
const mapAccount = (dto: DraftResource, ctx: QueryContext, actionAllowed?:boolean): ProjectAccountView => {
  validateResourceScope(dto,ctx,"integration")
  const provider=dto.provider
  if (!provider || !knownProvider.some(value=>value===provider)) return missingContract("integration_provider_projection_missing")
  return {
    id:dto.resource_id,owner:mapResourceOwner(dto),visibleIn:visibility(ctx.scope),inherited:dto.inherited,
    provider:provider as ProjectAccountView["provider"],alias:dto.name,authType:dto.auth_type,
    displayName:dto.display_name,revision:String(dto.version),
    projectAccessRevision:dto.project_access_revision,teamAccessRevision:dto.team_access_revision,
    ...(actionAllowed!==undefined?{allowedActions:{
      [dto.owner_scope==="team"?"accounts.teamManage":"accounts.manage"]:actionAllowed,
    }}:{}),
    // A5 now returns safe provider settings + credential presence, NOT a
    // tested connection or secret plaintext. Provider status stays unverified.
    baseUrl:typeof dto.provider_settings?.base_url==="string"?dto.provider_settings.base_url:null,
    enabled:null,updatedAt:dto.updated_at,credentialConfigured:dto.credential_configured,
    connectionStatus:dto.connection_status==="unverified"?"unverified":null,
    providerSettings:dto.provider_settings,
  }
}
const mapVariable = (dto: DraftResource, ctx:QueryContext, actionAllowed?:boolean): ProjectVariableView => {
  validateResourceScope(dto,ctx,"variable")
  return {
    id:dto.resource_id,visibleIn:visibility(ctx.scope),owner:mapResourceOwner(dto),inherited:dto.inherited,
    key:dto.name,kind:dto.is_secret?"secret":"plain",revision:String(dto.version),
    projectAccessRevision:dto.project_access_revision,teamAccessRevision:dto.team_access_revision,
    ...(actionAllowed!==undefined?{allowedActions:{
      [dto.owner_scope==="team"?"variables.teamManage":"variables.manage"]:actionAllowed,
    }}:{}),
    valueConfigured:dto.is_secret?dto.credential_configured:dto.value!==null,
    updatedAt:dto.updated_at,
    // Do NOT put even plain variable raw values in the UI domain cache by default.
  }
}
/**
 * Commands return DIRECT owner resource views (`inherited=false`) even when
 * they were issued from a Team-owned Project displaying an inherited list.
 * Never interpret a committed mutation as a failed cross-project read.
 */
function mutationResourceContext(
  ctx: QueryContext, dto: DraftResource, validatedOwner: ResourceOwner,
): QueryContext {
  if (dto.inherited) return missingContract("mutation_must_return_direct_owner")
  const owner = mapResourceOwner(dto)
  const actual = ownerToDraft(owner)
  const expected = ownerToDraft(validatedOwner)
  // Ownership preflight happens BEFORE sending any write. Post-write mapping
  // must never introduce a second network read that could misreport a commit.
  if (actual.owner_scope !== expected.owner_scope || actual.owner_id !== expected.owner_id)
    return missingContract("mutation_owner_mismatch")
  const ownerScope: ScopeSelection = owner.kind === "team"
    ? {kind:"team",teamId:owner.teamId}
    : {kind:"project",projectId:owner.projectId}
  return {...ctx,scope:ownerScope}
}
const mutationAccount = (ctx:QueryContext,dto:DraftResource,owner:ResourceOwner) =>
  mapAccount(dto,mutationResourceContext(ctx,dto,owner))
const mutationVariable = (ctx:QueryContext,dto:DraftResource,owner:ResourceOwner) =>
  mapVariable(dto,mutationResourceContext(ctx,dto,owner))

async function requireTeamCommand(
  source:DraftPlatformSourceApi,team:TeamView,action:"members"|"transfer",signal:AbortSignal,
):Promise<void>{
  const permit=await source.teamAccess(team.id,signal)
  if(!team.decisionVersion||permit.decision_version!==team.decisionVersion||
     (action==="members"&&!permit.can_manage_members)||
     (action==="transfer"&&!permit.can_transfer_team))return missingContract("team_action_permission_changed")
}
async function requireProjectCommand(
  source:DraftPlatformSourceApi,project:ProjectView,signal:AbortSignal,
):Promise<void>{
  const permit=await source.projectAccess(project.projectId,signal)
  if(!project.decisionVersion||permit.decision_version!==project.decisionVersion||
     !permit.can_transfer_project)return missingContract("project_transfer_permission_changed")
}
async function requireOperatorCommand(source:DraftPlatformSourceApi,ctx:QueryContext):Promise<void>{
  if(ctx.scope.kind!=="operator")return missingContract("operator_scope_required")
  const overview=await source.context(ctx.signal)
  if(!overview.global_operator)return missingContract("verified_operator_required")
}
function mutationRevision(version: string | number | undefined): MutationResult { return version===undefined?{}:{revision:String(draftVersion(version))} }

/** A5 DB records: no process/browser/Ghidra liveness or file content. */
function toOperationalRows(data:SourceProjectOperationalState,area:OperationalArea):OperationalItemView[] {
  const projectId=data.project_id
  const common={projectId,observedAt:data.observed_at,updatedAt:null}
  const sessions=data.runtime_sessions.map(row=>({
    ...common,id:row.runtime_session_uuid,label:row.kind,status:"unverified",reportedStatus:row.status,ledgerKind:"runtime-session" as const,
    version:row.version,cleanupState:row.cleanup_state,hardExpiresAt:row.hard_expires_at,
  }))
  const jobs=data.jobs.map(row=>({
    ...common,id:row.job_uuid,label:row.operation,status:"unverified",reportedStatus:row.status,ledgerKind:"job" as const,
    version:row.version,hardExpiresAt:row.hard_expires_at,
  }))
  const quota:OperationalItemView[]=data.quota?[{
    ...common,id:projectId,label:"File quota (DB)",status:"recorded",reportedStatus:data.quota.frozen?"frozen":"not-frozen",
    ledgerKind:"file-quota",version:data.quota.version,fileCount:data.quota.file_count,
    byteLimit:data.quota.byte_limit,usedBytes:data.quota.used_bytes,reservedBytes:data.quota.reserved_bytes,
  }]:[]
  const native=data.native_projects.map(row=>({
    ...common,id:row.native_project_id,label:"Native Project (DB)",status:"unverified",reportedStatus:row.enabled?"enabled":"disabled",
    ledgerKind:"native-project" as const,version:row.version,
  }))
  const imports=data.native_imports.map(row=>({
    ...common,id:row.import_uuid,label:"Native import (DB)",status:"unverified",reportedStatus:row.status,
    ledgerKind:"native-import" as const,version:row.version,cleanupState:row.cleanup_state,
  }))
  switch(area){
    case "dashboard":return [...sessions,...jobs,...quota,...native,...imports]
    case "files":return quota
    case "terminal":return [...sessions.filter(item=>item.label==="terminal"),...jobs.filter(item=>sessions.some(s=>s.id===data.jobs.find(j=>j.job_uuid===item.id)?.runtime_session_uuid && s.label==="terminal"))]
    case "analysis":return [...native,...imports]
    // A5 does NOT identify Calls/OAuth/Web/chromium/attached Chrome/Settings
    // Project data. Unknown types are not "empty" verified results.
    default:return missingContract("project_operational_area_unpublished")
  }
}

/** Bound readonly fan-out; huge Team/Project membership must not launch N simultaneous calls. */
async function mapLimited<T, R>(
  items: readonly T[], signal: AbortSignal, fn: (item: T) => Promise<R>,
  maxConcurrency = 4,
): Promise<R[]> {
  const result: R[] = new Array<R>(items.length)
  let index = 0
  const worker = async (): Promise<void> => {
    while (index < items.length) {
      if (signal.aborted) throw new DraftContractError("snapshot_aborted")
      const currentIndex = index++
      const item = items[currentIndex]
      if (item === undefined) throw new DraftContractError("snapshot_read_out_of_bounds")
      result[currentIndex] = await fn(item)
    }
  }
  await Promise.all(Array.from({length:Math.min(items.length,maxConcurrency)}, () => worker()))
  return result
}

async function mapTeam(client: DraftPlatformSourceApi, item: DraftTeam, signal:AbortSignal):Promise<TeamView> {
  const [members,permit] = await Promise.all([
    client.memberDetails(item.team_id,signal),client.teamAccess(item.team_id,signal),
  ])
  const owner=members.find(member=>member.user_id===item.owner_user_id)
  return {
    id:item.team_id,name:item.name,ownerId:item.owner_user_id,ownerLabel:owner?.username??item.owner_user_id,
    revision:String(item.version),decisionVersion:permit.decision_version,
    allowedActions:teamActions(permit),
    members:members.map(member=>({
      userId:member.user_id,label:member.username,active:member.active&&member.enabled,
      owner:member.user_id===item.owner_user_id,
    })),
  }
}

/** Verify current A4 decision/owner/action before ANY resource write. */
async function requireOwner(client:DraftPlatformSourceApi,ctx:QueryContext,owner:ResourceOwner):Promise<void> {
  const selector=ownerToDraft(owner)
  if(ctx.scope.kind==="team"){
    if(selector.owner_scope!=="team"||selector.owner_id!==draftUuid(ctx.scope.teamId))
      return missingContract("team_resource_owner_mismatch")
    const permit=await client.teamAccess(ctx.scope.teamId,ctx.signal)
    requireSourceDecision(ctx,permit.decision_version)
    if(!permit.can_manage_resources)return missingContract("team_resource_permission_revoked")
    return
  }
  if(ctx.scope.kind!=="project")return missingContract("resource_owner_scope_missing")
  const permit=await client.projectAccess(ctx.scope.projectId,ctx.signal)
  requireSourceDecision(ctx,permit.decision_version)
  if(selector.owner_scope==="project"){
    if(selector.owner_id!==draftUuid(ctx.scope.projectId)||!permit.can_manage_project_resources)
      return missingContract("project_resource_permission_revoked")
  }else if(permit.owner_scope!=="team"||permit.owner_id!==selector.owner_id||!permit.can_manage_team_resources){
    return missingContract("project_team_resource_permission_revoked")
  }
}

/** A4 ResourceView access revisions MUST match the verified A4 action snapshot. */
async function resourcePermit(
  client:DraftPlatformSourceApi,ctx:QueryContext,rows:readonly DraftResource[],
):Promise<(row:DraftResource)=>boolean>{
  if(ctx.scope.kind==="team"){
    const permit=await client.teamAccess(ctx.scope.teamId,ctx.signal)
    requireSourceDecision(ctx,permit.decision_version)
    for(const row of rows)requireDecisionMatch(row.team_access_revision,permit.decision_version,"team")
    return ()=>permit.can_manage_resources
  }
  if(ctx.scope.kind!=="project")return missingContract("resource_scope_not_verified")
  const permit=await client.projectAccess(ctx.scope.projectId,ctx.signal)
  requireSourceDecision(ctx,permit.decision_version)
  for(const row of rows)requireDecisionMatch(row.project_access_revision,permit.decision_version,"project")
  return row=>row.owner_scope==="team" ?
    permit.owner_scope==="team"&&permit.owner_id===row.owner_id&&permit.can_manage_team_resources :
    permit.can_manage_project_resources&&row.owner_id===permit.project_id
}

/** Never trust a Project-visible Team resource unless it matches the Project's CURRENT owner Team. */
async function requireEffectiveScope(client:DraftPlatformSourceApi, ctx:QueryContext, resources:readonly DraftResource[]):Promise<void> {
  if (ctx.scope.kind === "team") {
    const currentTeamId=ctx.scope.teamId
    if(resources.some(row=>row.owner_scope!=="team"||row.owner_id!==currentTeamId||row.inherited))return missingContract("foreign_team_resource_rejected")
    return
  }
  if (ctx.scope.kind !== "project")return missingContract("project_scope_required")
  const requestedId=ctx.scope.projectId
  const projects=await client.projects(ctx.signal)
  const owner=projects.find(item=>item.project_id===requestedId)
  if(!owner)return missingContract("project_scope_unavailable")
  if(resources.some(row=>row.owner_scope==="team"&&(owner.owner_team_id!==row.owner_id||!row.inherited)))return missingContract("foreign_team_inheritance_rejected")
  if(resources.some(row=>row.owner_scope==="project"&&(row.owner_id!==requestedId||row.inherited)))return missingContract("foreign_project_resource_rejected")
}

/** Resource ID and owner must both be confirmed, never resolved by an alias. */
async function readScopedResource(client:DraftPlatformSourceApi, ctx:QueryContext, kind:"integrations"|"variables", id:string):Promise<DraftResource> {
  const resourceId = draftUuid(id)
  let match:DraftResource|undefined
  if (ctx.scope.kind === "team") {
    const items = await client.teamResources(ctx.scope.teamId,kind,ctx.signal)
    match = items.find(item => item.resource_id === resourceId)
  } else if (ctx.scope.kind === "project") {
    match = await client.resolveResource(ctx.scope.projectId,kind,{scope:"all",resourceId},ctx.signal)
  }
  if (!match) return missingContract("qualified_resource_not_visible")
  validateResourceScope(match,ctx,kind==="integrations"?"integration":"variable")
  await requireEffectiveScope(client,ctx,[match])
  await resourcePermit(client,ctx,[match])
  return match
}

export interface DraftConsumer {
  /** Direct typed source APIs remain available to integration authors; no live installation. */
  source: DraftPlatformSourceApi
  /** The normalized frontend UI port, disabled by default and incomplete where Pydantic lacks DTOs. */
  port: PlatformPort
  destroy(): void
}

/**
 * Create a private source consumer only. Caller must explicitly supply an
 * audited origin ending `/v1/platform`; current C1-B2/C2 forbids installing it.
 */
export function createUninstalledDraftConsumer(baseUrl: string): DraftConsumer {
  const source=new DraftPlatformSourceApi(baseUrl)
  const getTeams=async(signal:AbortSignal)=>new Map((await source.teams(signal)).map(item=>[item.team_id,item] as const))
  /** Consistent source-only snapshot assembled from verified A4 projections. */
  const snapshotKey=(current:DraftMeContext):string=>JSON.stringify([
    current.user.user_id,current.user.role,current.user.enabled,current.user.credential_version,current.global_operator,
    current.user.allowed_actions.slice().sort(),
    current.teams.map(item=>`${item.team_id}:${item.decision_version}`).sort(),
    current.projects.map(item=>`${item.project_id}:${item.decision_version}:${item.owner_scope}:${item.owner_id}`).sort(),
  ])
  const readProjection=async(signal:AbortSignal):Promise<AccessProjection>=>{
    const [current,teams,projects]=await Promise.all([
      source.context(signal),source.teams(signal),source.projects(signal),
    ])
    // A4 list endpoints are individually authenticated but not a single DB
    // snapshot. Recheck decision versions AFTER the independent list queries,
    // otherwise Team/Project transfers can mix old owner metadata with new ACL.
    const after=await source.context(signal)
    if(snapshotKey(current)!==snapshotKey(after))return missingContract("identity_decision_snapshot_changed")
    const byTeam=new Map(teams.map(item=>[item.team_id,item] as const))
    const byProject=new Map(projects.map(item=>[item.project_id,item] as const))
    const teamDecisions=new Map(current.teams.map(item=>[item.team_id,item] as const))
    const projectDecisions=new Map(current.projects.map(item=>[item.project_id,item] as const))
    // Cross-request owner/membership churn is a DENY/refresh, not a random UI selection.
    if(byTeam.size!==teams.length||byProject.size!==projects.length||
       byTeam.size!==teamDecisions.size||byProject.size!==projectDecisions.size||
       teams.some(item=>!teamDecisions.has(item.team_id))||
       projects.some(item=>!projectDecisions.has(item.project_id))) {
      return missingContract("identity_scope_snapshot_inconsistent")
    }
    for(const row of projects) {
      const decision=projectDecisions.get(row.project_id)
      if(!decision)return missingContract("project_decision_missing")
      validateOwnerDecision(row,decision)
      if(row.owner_team_id && !byTeam.has(row.owner_team_id))return missingContract("team_owner_projection_missing")
    }
    const available=projects.map(row=>mapProject(row,byTeam,projectDecisions.get(row.project_id)))
    return {
      user:{
        userId:current.user.user_id,username:current.user.username,displayName:current.user.username,
        active:current.user.enabled,isSuperuser:current.global_operator,
      },
      teams:teams.map(team=>({teamId:team.team_id,name:team.name})),
      projects:available,
      permissions:accountActions(current),
      teamPermissions:Object.fromEntries(current.teams.map(decision=>[decision.team_id,teamActions(decision)])),
      projectPermissions:Object.fromEntries(current.projects.map(decision=>[decision.project_id,projectActions(decision)])),
      operatorPermissions:operatorActions(current),
      sourceProjectPermissionCodes:Object.fromEntries(current.projects.map(decision=>[decision.project_id,decision.permissions])),
      teamDecisionVersions:Object.fromEntries(current.teams.map(decision=>[decision.team_id,decision.decision_version])),
      projectDecisionVersions:Object.fromEntries(current.projects.map(decision=>[decision.project_id,decision.decision_version])),
    }
  }
  const port:PlatformPort={
    capabilities:{
      candidateVerification:false,scopedRealtime:false,operationalSummary:true,
      sessionLabels:false,normalSessionOpen:true,elevatedSessionOpen:false,sessionApprovalTtlEdit:false,
    },
    auth:{
      invalidate(){source.http.clearCredential()},
      onCredentialInvalidated(listener){
        return source.http.onCredentialChange(change=>{
          if(change!=="established")listener()
        })
      },
      async restore(signal){return source.hasToken?readProjection(signal):null},
      async login(input,signal){
        await source.login(input.username,input.password,signal)
        try{return await readProjection(signal)}
        catch(error){source.http.clearCredential();throw error}
      },
      async logout(signal){await source.logout(signal)},
      async refresh(signal){
        // A4 /me/context reads DO NOT rotate an access credential. Credential
        // rotation is a separate explicit operation; rotating on every User,
        // Team or Resource refresh can invalidate concurrent pending requests.
        return source.hasToken?readProjection(signal):null
      },
      async renew(signal){
        if(!source.hasToken)return null
        await source.refreshToken(signal)
        try { return await readProjection(signal) }
        catch(error){source.http.clearCredential();throw error}
      },
      async register(input,signal,idempotencyKey){await source.register({invitation:input.invitationToken,username:input.username,password:input.password},idempotencyKey,signal)},
      async redeemPasswordReset(input,signal,idempotencyKey){await source.resetPassword({token:input.resetToken,new_password:input.password},idempotencyKey,signal)},
    },
    users:{
      async list(ctx){
        if(ctx.scope.kind!=="operator")return missingContract("operator_scope_required")
        const [current,users,teams,projects]=await Promise.all([
          source.context(ctx.signal),source.users(ctx.signal),source.teams(ctx.signal),source.projects(ctx.signal),
        ])
        if(!current.global_operator || !current.user.allowed_actions.includes("identity.users.list"))return missingContract("verified_user_directory_required")
        return {items:users.map(user=>mapUser(
          user,teams.filter(team=>team.owner_user_id===user.user_id).length,
          projects.filter(project=>project.owner_user_id===user.user_id).length,current,
        ))}
      },
      async invitations(ctx){
        const [current,items]=await Promise.all([source.context(ctx.signal),source.invitations(ctx.signal)])
        return {items:items.map(item=>{
          if(!["registration","password_reset"].includes(item.kind))return missingContract("invitation_kind_unsupported")
          if(!current.global_operator && item.issuer_id!==current.user.user_id)return missingContract("invitation_scope_mismatch")
          return {
            id:item.invitation_id,kind:item.kind as "registration"|"password_reset",createdAt:item.created_at,
            issuerLabel:item.issuer_id??"—",expiresAt:item.expires_at,
            consumedAt:item.used_at,revokedAt:item.revoked_at,
          }
        })}
      },
      async issueInvitation(ctx){const result=await source.issueInvitation(ctx.idempotencyKey,ctx.signal);return {invitationUrl:result.url,expiresAt:null}},
      async revokeInvitation(ctx,id){const result=await source.revokeInvitation(id,ctx.idempotencyKey,ctx.signal);if(!result.revoked) return missingContract("invitation_revoke_unconfirmed");return {}},
      async changePassword(ctx,current,next){
        const result=await source.changePassword({current_password:current,new_password:next},ctx.idempotencyKey,ctx.signal)
        if(!result.changed)return missingContract("password_change_unconfirmed")
        // Caller drops old credential AFTER submit settles; emitting expiry here
        // would incorrectly mark this ACKed password change as unsuccessful.
        return {}
      },
      async issueReset(ctx,userId){await requireOperatorCommand(source,ctx);const result=await source.issuePasswordReset(userId,ctx.idempotencyKey,ctx.signal);return {invitationUrl:result.url,expiresAt:null}},
      async setActive(ctx,user,active){await requireOperatorCommand(source,ctx);const result=active?await source.restoreUser(user.id,ctx.idempotencyKey,ctx.signal):await source.suspend(user.id,ctx.idempotencyKey,ctx.signal);if(result.enabled!==active)return missingContract("user_status_mismatch");return {}},
      async setSuperuser(ctx,user,enabled){await requireOperatorCommand(source,ctx);const result=await source.setSuperuser(user.id,enabled,ctx.idempotencyKey,ctx.signal);if((result.role==="superuser")!==enabled)return missingContract("user_role_mismatch");return {}},
      async remove(ctx,user){await requireOperatorCommand(source,ctx);const result=await source.deleteUser(user.id,ctx.idempotencyKey,ctx.signal);if(result.user_id!==user.id)return missingContract("user_delete_response_mismatch");return {}},
    },
    teams:{
      async list(ctx){const raw=await source.teams(ctx.signal);return {items:await mapLimited(raw,ctx.signal,team=>mapTeam(source,team,ctx.signal))}},
      async create(ctx,name){
        const raw=await source.createTeam(name,ctx.idempotencyKey,ctx.signal)
        // Team creation response does not include members. Do NOT issue a
        // fragile second read that could mark a committed write as failed.
        return {id:raw.team_id,name:raw.name,ownerId:raw.owner_user_id,ownerLabel:raw.owner_user_id,members:null,revision:String(raw.version)}
      },
      async addMember(ctx,team,userId){await requireTeamCommand(source,team,"members",ctx.signal);const result=await source.addMember(team.id,userId,draftVersion(team.revision),ctx.idempotencyKey,ctx.signal);if(!result.active)return missingContract("team_member_add_unconfirmed");return {}},
      async removeMember(ctx,team,userId){await requireTeamCommand(source,team,"members",ctx.signal);const result=await source.removeMember(team.id,userId,draftVersion(team.revision),ctx.idempotencyKey,ctx.signal);if(result.active)return missingContract("team_member_remove_unconfirmed");return {}},
      async transferOwner(ctx,team,newOwnerId){await requireTeamCommand(source,team,"transfer",ctx.signal);const result=await source.transferTeamOwner(team.id,newOwnerId,draftVersion(team.revision),ctx.idempotencyKey,ctx.signal);if(result.owner_user_id!==newOwnerId)return missingContract("team_owner_mismatch");return mutationRevision(result.version)},
    },
    projects:{
      async list(ctx){
        const [raw,teams,context]=await Promise.all([source.projects(ctx.signal),getTeams(ctx.signal),source.context(ctx.signal)])
        const decisions=new Map(context.projects.map(item=>[item.project_id,item] as const))
        if(raw.length!==decisions.size || raw.some(item=>!decisions.has(item.project_id)))return missingContract("projects_source_decisions_incomplete")
        return {items:raw.map(item=>mapProject(item,teams,decisions.get(item.project_id)))}
      },
      async create(ctx,input){
        const byTeam=await getTeams(ctx.signal) // Preflight projection BEFORE the mutation.
        if(input.owner.kind==="user"){
          const me=await source.me(ctx.signal)
          if(me.user_id!==input.owner.userId)return missingContract("other_user_project_creation_unsupported")
        } else if(!byTeam.has(input.owner.teamId))return missingContract("team_owner_projection_missing")
        const created=await source.createProject({name:input.name,owner_team_id:input.owner.kind==="team"?input.owner.teamId:null},ctx.idempotencyKey,ctx.signal)
        if(created.owner_team_id !== (input.owner.kind==="team"?input.owner.teamId:null))return missingContract("created_project_owner_mismatch")
        return mapProject(created,byTeam)
      },
      async transfer(ctx,project,newOwner){
        await requireProjectCommand(source,project,ctx.signal)
        if(newOwner.kind==="user"){
          const me=await source.me(ctx.signal)
          if(me.user_id!==newOwner.userId)return missingContract("reassignment_requires_admin_route")
        }
        const result=await source.transferProject(project.projectId,{
          expected_version:draftVersion(project.revision),confirmed:true,
          owner_team_id:newOwner.kind==="team"?newOwner.teamId:null,
          withdraw_to_personal:newOwner.kind==="user",
        },ctx.idempotencyKey,ctx.signal)
        return mutationRevision(result.version)
      },
      async adminReassign(ctx,project,newOwner){
        await requireOperatorCommand(source,ctx)
        const before=await source.projectAccess(project.projectId,ctx.signal)
        if(before.decision_version!==project.decisionVersion)return missingContract("reassign_project_decision_changed")
        const input={
          expected_version:draftVersion(project.revision),confirmed:true as const,
          new_owner_user_id:newOwner.kind==="user"?newOwner.userId:null,
          new_owner_team_id:newOwner.kind==="team"?newOwner.teamId:null,
        }
        const result=await source.adminReassignProject(project.projectId,input,ctx.idempotencyKey,ctx.signal)
        if((newOwner.kind==="user"&&result.owner_user_id!==newOwner.userId)||
           (newOwner.kind==="team"&&result.owner_team_id!==newOwner.teamId)) {
          return missingContract("admin_reassign_owner_response_mismatch")
        }
        return mutationRevision(result.version)
      },
    },
    agents:{
      async list(ctx){const id=scopeProject(ctx);const permit=await source.projectAccess(id,ctx.signal);requireSourceDecision(ctx,permit.decision_version);const items=await source.agents(id,ctx.signal);return {items:items.map(mapAgent)}},
      async create(ctx,input){const id=scopeProject(ctx);const permit=await source.projectAccess(id,ctx.signal);requireSourceDecision(ctx,permit.decision_version);if(!permit.can_manage_agents)return missingContract("agent_manage_revoked");const result=await source.createAgent(id,{name:input.label,parent_agent_id:input.parentAgentId},ctx.idempotencyKey,ctx.signal);if(result.project_id!==id)return missingContract("agent_create_scope_mismatch");return mapAgent(result)},
      async rename(ctx,agent,label){const id=scopeProject(ctx);if(id!==agent.projectId)return missingContract("agent_scope_mismatch");const permit=await source.projectAccess(id,ctx.signal);requireSourceDecision(ctx,permit.decision_version);if(!permit.can_manage_agents)return missingContract("agent_manage_revoked");const result=await source.renameAgent(id,agent.id,{name:label,expected_version:draftVersion(agent.revision)},ctx.idempotencyKey,ctx.signal);return mutationRevision(result.version)},
      async setEnabled(ctx,agent,enabled){
        const id=scopeProject(ctx)
        if(id!==agent.projectId)return missingContract("agent_scope_mismatch")
        const permit=await source.projectAccess(id,ctx.signal)
        requireSourceDecision(ctx,permit.decision_version)
        if(!permit.can_manage_agents)return missingContract("agent_manage_revoked")
        const result=await source.setAgentEnabled(id,agent.id,{enabled,expected_version:draftVersion(agent.revision),confirmed:true},ctx.idempotencyKey,ctx.signal)
        return mutationRevision(result.version)
      },
    },
    sessions:{
      async list(ctx){
        const id=scopeProject(ctx)
        const before=await source.projectAccess(id,ctx.signal)
        const [rows,approvals,catalog]=await Promise.all([
          source.sessions(id,ctx.signal),source.approvals(id,ctx.signal),source.grantCatalog(id,ctx.signal),
        ])
        const after=await source.projectAccess(id,ctx.signal)
        if(before.decision_version!==after.decision_version)return missingContract("session_decision_changed")
        requireSourceDecision(ctx,after.decision_version)
        if(new Set(rows.map(item=>item.session_uuid)).size!==rows.length||
           new Set(approvals.map(item=>item.request_id)).size!==approvals.length)
          return missingContract("session_approval_snapshot_duplicate")
        // A4 limits each list to 250. An approval's base session can be
        // outside the current page; that approval remains visible but cannot
        // be approved until a fresh authoritative base is available.
        return {
          sessions:rows.map(item=>mapSession(item,after)),
          requests:approvals.map(item=>mapApproval(item,after,rows)),
          availableGrants:catalog.supported_grants.map(id=>({id,label:id})),
          normalHardTtlSeconds:catalog.normal_hard_ttl_seconds,
          elevatedMaxSeconds:catalog.elevated_max_seconds,
        }
      },
      async open(ctx,input){
        if(input.kind!=="normal"||input.label.trim())return missingContract("session_label_or_elevated_open_unsupported")
        const id=scopeProject(ctx)
        requireSourceDecision(ctx,(await source.projectAccess(id,ctx.signal)).decision_version)
        const result=await source.openNormalSession(id,{elevation_policy:input.elevationPolicy},ctx.idempotencyKey,ctx.signal)
        if(result.project_id!==id||result.is_elevated)return missingContract("normal_session_response_invalid")
        return mapSession(result)
      },
      async request(ctx,input){
        const id=scopeProject(ctx)
        if(!canonicalUuid4(input.sessionUuid))return missingContract("session_uuid_invalid")
        const [rows,catalog,permit]=await Promise.all([source.sessions(id,ctx.signal),source.grantCatalog(id,ctx.signal),source.projectAccess(id,ctx.signal)])
        requireSourceDecision(ctx,permit.decision_version)
        const session=rows.find(item=>item.session_uuid===input.sessionUuid)
        if(!session||session.status!=="active"||session.is_elevated||session.elevation_policy!=="requestable"||
           Date.parse(session.hard_expires_at)<=Date.now())return missingContract("session_not_requestable")
        if(!input.grants.length||input.grants.length>32||input.grants.some(item=>!catalog.supported_grants.includes(item)))
          return missingContract("session_unknown_grant")
        let seconds=Math.min(300,catalog.elevated_max_seconds)
        if(input.requestedUntil){
          seconds=Math.ceil((Date.parse(input.requestedUntil)-Date.now())/1000)
          if(!Number.isFinite(seconds)||seconds<1||seconds>300||seconds>catalog.elevated_max_seconds)
            return missingContract("session_request_ttl_out_of_bounds")
        }
        await source.requestElevation(id,input.sessionUuid,{grants:[...input.grants],seconds},ctx.idempotencyKey,ctx.signal)
        return {}
      },
      async resolve(ctx,request,approve,grants,until,confirmation){
        const id=scopeProject(ctx)
        if(request.projectId!==id||!canonicalUuid4(request.sessionUuid)||!request.snapshotKey)
          return missingContract("approval_scope_or_snapshot_missing")
        const [permit,approvals,catalog,rows]=await Promise.all([
          source.projectAccess(id,ctx.signal),source.approvals(id,ctx.signal),
          source.grantCatalog(id,ctx.signal),source.sessions(id,ctx.signal),
        ])
        requireSourceDecision(ctx,permit.decision_version)
        if(!permit.can_approve_agent_sessions)return missingContract("approval_permission_revoked")
        const current=approvals.find(item=>item.request_id===request.id)
        const base=rows.find(item=>item.session_uuid===request.sessionUuid)
        if(!current||current.status!=="pending"||approvalSnapshot(current)!==request.snapshotKey||
           !base||base.status!=="active"||Date.parse(base.hard_expires_at)<=Date.now()||
           Date.parse(current.requested_expires_at)<=Date.now())return missingContract("approval_snapshot_stale")
        if(until!==null&&Date.parse(until)!==Date.parse(current.requested_expires_at))
          return missingContract("approval_ttl_edit_not_supported")
        if(approve&&(!grants.length||grants.length>32||grants.some(item=>!catalog.supported_grants.includes(item))))
          return missingContract("approval_unknown_grant")
        if(approve&&grants.some(item=>!current.requested_grants.includes(item))&&!confirmation.explicitExpansion)
          return missingContract("grant_expansion_confirmation_required")
        if(!request.revision || draftVersion(request.revision)!==current.version)return missingContract("approval_version_stale")
        const result=await source.resolveElevation(id,request.id,{
          expected_version:current.version,
          approve,allowed_grants:approve?[...grants]:null,
          explicit_expansion_confirmation:approve&&confirmation.explicitExpansion,
        },ctx.idempotencyKey,ctx.signal)
        if(approve&&(!result.session||result.session.project_id!==id||!result.session.is_elevated))
          return missingContract("approval_response_invalid")
        if(!approve&&result.session!==null)return missingContract("rejection_response_invalid")
        return result.session?mutationRevision(result.session.version):{}
      },
      async revoke(ctx,session){
        const id=scopeProject(ctx)
        if(session.projectId!==id||!canonicalUuid4(session.sessionUuid))return missingContract("session_scope_mismatch")
        const [rows,permit]=await Promise.all([source.sessions(id,ctx.signal),source.projectAccess(id,ctx.signal)])
        requireSourceDecision(ctx,permit.decision_version)
        const current=rows.find(item=>item.session_uuid===session.sessionUuid)
        if(!current||current.status!=="active"||Date.parse(current.hard_expires_at)<=Date.now()||
           draftVersion(session.revision)!==current.version)return missingContract("session_revocation_stale")
        const result=await source.revokeSession(id,session.sessionUuid,ctx.idempotencyKey,ctx.signal)
        if(result.project_id!==id||result.session_uuid!==session.sessionUuid||result.status!=="revoked")
          return missingContract("session_revoke_response_invalid")
        return mutationRevision(result.version)
      },
    },
    accounts:{
      async list(ctx,selector){
        scopeResource(ctx)
        const items=ctx.scope.kind==="team"?
          await source.teamResources(ctx.scope.teamId,"integrations",ctx.signal):
          await source.projectResources(scopeProject(ctx),"integrations",selector.scope,ctx.signal)
        await requireEffectiveScope(source,ctx,items)
        const allowed=await resourcePermit(source,ctx,items)
        return {items:items.map(dto=>mapAccount(dto,ctx,allowed(dto)))}
      },
      async save(ctx,input,id){
        scopeResource(ctx)
        await requireOwner(source,ctx,input.owner)
        const owner=ownerToDraft(input.owner)
        if(input.enabled===false)return missingContract("integration_enabled_field_unavailable")
        if(id){
          if(!input.expectedRevision)return missingContract("integration_revision_required")
          const previous=await readScopedResource(source,ctx,"integrations",id)
          if(previous.owner_scope!==owner.owner_scope||previous.owner_id!==owner.owner_id||previous.provider!==input.provider)return missingContract("integration_owner_or_provider_mismatch")
          if(input.credential?.length)return missingContract("integration_rotation_requires_separate_command")
          // Source UpdateIntegration accepts alias and optionally provider_settings,
          // never a guessed enabled/base_url field or an implicit secret change.
          const update={expected_version:draftVersion(input.expectedRevision),alias:input.alias,
            ...(input.providerSettings?{provider_settings:input.providerSettings}:{})}
          const result=await source.updateIntegration(id,update,ctx.idempotencyKey,ctx.signal)
          return mutationAccount(ctx,result,input.owner)
        }
        if(!input.credential||!input.authType||!input.providerSettings)return missingContract("integration_creation_schema_incomplete")
        const catalog=await source.providerCatalog(ctx.signal)
        const definition=catalog.providers.find(item=>item.provider===input.provider)
        if(!definition||!definition.auth_types.includes(input.authType))return missingContract("source_provider_type_unsupported")
        const result=await source.createIntegration({...owner,alias:input.alias,provider:input.provider,auth_type:input.authType,provider_settings:input.providerSettings,credential:input.credential},ctx.idempotencyKey,ctx.signal)
        return mutationAccount(ctx,result,input.owner)
      },
      async verify(){return missingContract("provider_candidate_verification_route_missing")},
      async rotate(ctx,account,credential){
        scopeResource(ctx)
        if(!credential.trim())return missingContract("integration_rotation_secret_required")
        const previous=await readScopedResource(source,ctx,"integrations",account.id)
        const owner=ownerToDraft(account.owner)
        if(previous.owner_scope!==owner.owner_scope||previous.owner_id!==owner.owner_id||previous.provider!==account.provider)return missingContract("integration_rotation_owner_mismatch")
        const result=await source.rotateIntegration(account.id,{expected_version:draftVersion(account.revision),credential},ctx.idempotencyKey,ctx.signal)
        return mutationAccount(ctx,result,account.owner)
      },
      async remove(ctx,account){
        scopeResource(ctx)
        const previous=await readScopedResource(source,ctx,"integrations",account.id)
        const owner=ownerToDraft(account.owner)
        if(previous.owner_scope!==owner.owner_scope||previous.owner_id!==owner.owner_id)return missingContract("integration_delete_owner_mismatch")
        const result=await source.revokeIntegration(account.id,draftVersion(account.revision),ctx.idempotencyKey,ctx.signal)
        if(!result.revoked)return missingContract("integration_revoke_unconfirmed")
        return mutationRevision(result.new_version)
      },
    },
    variables:{
      async list(ctx,selector){
        scopeResource(ctx)
        const items=ctx.scope.kind==="team"?
          await source.teamResources(ctx.scope.teamId,"variables",ctx.signal):
          await source.projectResources(scopeProject(ctx),"variables",selector.scope,ctx.signal)
        await requireEffectiveScope(source,ctx,items)
        const allowed=await resourcePermit(source,ctx,items)
        return {items:items.map(dto=>mapVariable(dto,ctx,allowed(dto)))}
      },
      async save(ctx,input,id){
        scopeResource(ctx)
        await requireOwner(source,ctx,input.owner)
        const owner=ownerToDraft(input.owner)
        if(id){
          if(!input.expectedRevision)return missingContract("variable_revision_required")
          const previous=await readScopedResource(source,ctx,"variables",id)
          if(previous.owner_scope!==owner.owner_scope||previous.owner_id!==owner.owner_id)return missingContract("variable_owner_mismatch")
          if(input.action==="rename" && input.value===undefined){
            const result=await source.updateVariable(id,{expected_version:draftVersion(input.expectedRevision),name:input.key},ctx.idempotencyKey,ctx.signal)
            return mutationVariable(ctx,result,input.owner)
          }
          if(input.action==="rotate" && input.value!==undefined && previous.name===input.key){
            const result=await source.rotateVariable(id,{expected_version:draftVersion(input.expectedRevision),value:input.value,is_secret:input.kind==="secret"},ctx.idempotencyKey,ctx.signal)
            return mutationVariable(ctx,result,input.owner)
          }
          return missingContract("variable_rename_and_rotate_are_separate_commands")
        }
        if(input.value===undefined)return missingContract("variable_value_required")
        const result=await source.createVariable({...owner,name:input.key,value:input.value,is_secret:input.kind==="secret"},ctx.idempotencyKey,ctx.signal)
        return mutationVariable(ctx,result,input.owner)
      },
      async remove(ctx,variable){
        scopeResource(ctx)
        const previous=await readScopedResource(source,ctx,"variables",variable.id)
        const owner=ownerToDraft(variable.owner)
        if(previous.owner_scope!==owner.owner_scope||previous.owner_id!==owner.owner_id)return missingContract("variable_delete_owner_mismatch")
        const result=await source.revokeVariable(variable.id,draftVersion(variable.revision),ctx.idempotencyKey,ctx.signal)
        if(!result.revoked)return missingContract("variable_revoke_unconfirmed")
        return mutationRevision(result.new_version)
      },
    },
    providers:{
      async catalog(ctx){
        if(!source.hasToken)return missingContract("authenticated_provider_catalog_required")
        const [current,catalog]=await Promise.all([source.context(ctx.signal),source.providerCatalog(ctx.signal)])
        if(!current.user.enabled)return missingContract("disabled_user_provider_catalog")
        return {providers:catalog.providers.map(item=>({provider:item.provider,authTypes:item.auth_types,connectivityStatus:item.connectivity_status})),
          networkVerificationAvailable:catalog.network_verification_available}
      },
    },
    commandStatus:{
      async get(ctx,input){
        const id=scopeProject(ctx)
        const before=await source.projectAccess(id,ctx.signal)
        requireSourceDecision(ctx,before.decision_version)
        const status=await source.commandStatus(id,input.operation,input.idempotencyKey,ctx.signal)
        const after=await source.projectAccess(id,ctx.signal)
        if(after.decision_version!==before.decision_version)return missingContract("command_status_scope_changed")
        return {projectId:status.project_id,operation:status.operation,state:status.state,
          outcomeHttpStatus:status.outcome_http_status,expiresAt:status.expires_at,reconciliationRequired:status.reconciliation_required}
      },
    },
    operations:{
      async list(ctx,area){
        const projectId=scopeProject(ctx)
        // A5's project_permit authenticates every DB read; duplicate frontend
        // revisions prevent cross-request role/owner drift.
        const before=await source.projectAccess(projectId,ctx.signal)
        requireSourceDecision(ctx,before.decision_version)
        const state=await source.operationalState(projectId,50,ctx.signal)
        requireDecisionMatch(state.project_access_revision,before.decision_version,"project")
        const after=await source.projectAccess(projectId,ctx.signal)
        if(after.decision_version!==before.decision_version)return missingContract("operational_permission_changed")
        const candidateRows=area==="dashboard"?[state.runtime_sessions,state.jobs,state.native_projects,state.native_imports]:
          area==="terminal"?[state.runtime_sessions,state.jobs]:
          area==="analysis"?[state.native_projects,state.native_imports]:[]
        return {
          items:toOperationalRows(state,area),revision:state.project_access_revision,
          serverLimit:state.limit,observedAt:state.observed_at,
          possiblyTruncated:candidateRows.some(rows=>rows.length>=state.limit),
        }
      },
    },
    operator:{
      async summary(ctx){
        if(ctx.scope.kind!=="operator")return missingContract("operator_scope_required")
        const [current,result]=await Promise.all([source.context(ctx.signal),source.operatorSummary(ctx.signal)])
        if(!current.global_operator)return missingContract("operator_permission_revoked")
        return {users:result.users,teams:result.teams,projects:result.projects,agentSessions:result.agent_sessions}
      },
    },
    realtime:{async connect(){return missingContract("authenticated_scoped_ws_contract_missing")}},
    // No PROJECT runtime operations API; A4 operator summary is not scoped runtime data.
  }
  return {source,port,destroy:()=>source.http.destroy()}
}
