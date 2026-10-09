/**
 * SOURCE-ONLY C1-B2 DEVELOPMENT MODELS. NOT APPROVED PUBLIC OPENAPI.
 * Exact current Pydantic drafts:
 * services/admin-api/src/presentation/platform_api.py
 * services/admin-api/src/presentation/platform_auth_api.py
 * services/admin-api/src/presentation/resource_api.py
 * services/admin-api/src/presentation/platform_overview_api.py
 * services/admin-api/src/presentation/platform_state_api.py
 * services/admin-api/src/presentation/platform_command_status.py
 * Do not install this client before verified C1-B2/C2 activation.
 */
export interface DraftErrorEnvelope {
  error: { version: 1; code: string; message: string; status: number }
}
export interface DraftAdminLogin { username: string; password: string }
export interface DraftAdminToken { access_token: string; token_type: string; expires_at: string }
export interface DraftUser {
  user_id: string
  username: string
  role: string
  enabled: boolean
  credential_version: number
}
export interface DraftTeam { team_id: string; name: string; owner_user_id: string; version: number }
export interface DraftTeamMembership { team_id: string; user_id: string; active: boolean }
export interface DraftProject {
  project_id: string
  name: string
  owner_user_id: string | null
  owner_team_id: string | null
  version: number
}
export interface DraftAgent { agent_id: string; project_id: string; name: string; parent_agent_id: string | null; enabled: boolean; version: number }
export interface DraftAgentSession { session_uuid: string; project_id: string; grants: string[]; is_elevated: boolean; hard_expires_at: string; status: string; version: number; label: string | null; elevation_policy: "fixed" | "requestable" }
export interface DraftPermissionView { project_id: string; permissions: string[] }
export interface DraftInvitation { url: string }
export interface DraftApproval { request_id: string }
export type DraftResourceOwner = "team" | "project"
export type DraftResourceScope = "all" | DraftResourceOwner
export interface DraftResource {
  resource_id: string
  kind: "integration" | "variable"
  name: string
  version: number
  project_access_revision: string | null
  team_access_revision: string | null
  owner_scope: DraftResourceOwner
  owner_id: string
  origin: DraftResourceOwner
  inherited: boolean
  is_secret: boolean
  masked: boolean
  provider: string | null
  auth_type: string | null
  display_name: string
  provider_settings: Record<string, unknown> | null
  credential_configured: boolean
  connection_status: string | null
  updated_at: string | null
  value: string | null
}
export interface DraftResourceRevoked { resource_id: string; revoked: boolean; new_version: number }

export interface DraftCreateTeam { name: string }
export interface DraftAddMember { user_id: string; expected_team_version: number }
export interface DraftTransferTeamOwner { new_owner_user_id: string; expected_version: number; confirmed: true }
export interface DraftCreateProject { name: string; owner_team_id: string | null }
export interface DraftTransferProjectOwner { expected_version: number; confirmed: true; owner_team_id: string | null; withdraw_to_personal: boolean }
export interface DraftAdminReassignProject { expected_version: number; confirmed: true; new_owner_user_id: string | null; new_owner_team_id: string | null }
export interface DraftCreateAgent { name: string; parent_agent_id: string | null }
export interface DraftRenameAgent { name: string; expected_version: number }
export interface DraftSetAgentEnabled { enabled: boolean; expected_version: number; confirmed: true }
export interface DraftRegister { invitation: string; username: string; password: string }
export interface DraftChangePassword { current_password: string; new_password: string }
export interface DraftPasswordReset { token: string; new_password: string }
export interface DraftSuperuserRole { enabled: boolean; confirmed: true }
export interface DraftDangerousConfirmation { confirmed: true }
export interface DraftOpenSession { elevation_policy: "fixed" | "requestable" }
export interface DraftRequestElevation { grants: string[]; seconds: number }
export interface DraftResolveElevation { expected_version: number; approve: boolean; allowed_grants: string[] | null; explicit_expansion_confirmation: boolean }
export interface DraftCreateIntegration { owner_scope: DraftResourceOwner; owner_id: string; alias: string; provider: string; auth_type: string; provider_settings: Record<string, unknown>; credential: string }
export interface DraftUpdateIntegration { expected_version: number; alias?: string | null; provider_settings?: Record<string, unknown> | null }
export interface DraftRotateIntegration { expected_version: number; credential: string }
export interface DraftCreateVariable { owner_scope: DraftResourceOwner; owner_id: string; name: string; value: string; is_secret: boolean }
export interface DraftUpdateVariable { expected_version: number; name: string }
export interface DraftRotateVariable { expected_version: number; value: string; is_secret: boolean }

const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i
export class DraftContractError extends Error {
  readonly code: string
  readonly status: number | null
  constructor(code: string, status: number | null = null) {
    super("Draft C1-B2 contract unavailable or response mismatch")
    this.name = "DraftContractError"
    this.code = code
    this.status = status
  }
}
export function missingContract(code: string): never { throw new DraftContractError(code) }
export function draftSessionUuid(value: string): string {
  const checked = draftUuid(value)
  if (!/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/.test(checked)) {
    throw new DraftContractError("session_uuid_invalid")
  }
  return checked
}
export function draftUuid(value: string): string {
  if (!uuid.test(value)) throw new DraftContractError("invalid_uuid")
  return value.toLowerCase()
}
export function draftVersion(value: string | number | undefined): number {
  const numberValue = typeof value === "number" ? value : Number(value)
  if (!Number.isSafeInteger(numberValue) || numberValue < 1) throw new DraftContractError("version_required")
  return numberValue
}
export function draftRecord(raw: unknown): Record<string, unknown> {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) throw new DraftContractError("response_invalid")
  return raw as Record<string, unknown>
}
/** A4 has no schema-version negotiation; unknown authority fields fail closed. */
export function draftRecordFields(raw: unknown, fields: readonly string[]): Record<string, unknown> {
  const view=draftRecord(raw)
  if(Object.keys(view).some(key=>!fields.includes(key)))throw new DraftContractError("source_response_schema_unreviewed")
  return view
}
export function draftString(raw: unknown): string {
  if (typeof raw !== "string") throw new DraftContractError("response_invalid")
  return raw
}
export function draftBoolean(raw: unknown): boolean {
  if (typeof raw !== "boolean") throw new DraftContractError("response_invalid")
  return raw
}
export function draftInteger(raw: unknown): number {
  if (!Number.isSafeInteger(raw) || typeof raw !== "number") throw new DraftContractError("response_invalid")
  return raw
}
/** Apply ONLY a specifically documented accepted A5 Pydantic field default.
 * Unknown values are still parsed strictly; required fields never use this. */
export function draftSourceDefault<T>(raw:unknown, fallback:T, parser:(raw:unknown)=>T):T {
  return raw===undefined?fallback:parser(raw)
}
export function draftNullable<T>(raw: unknown, parser: (raw: unknown) => T): T | null {
  return raw === null ? null : parser(raw)
}
export function draftList<T>(raw: unknown, parser: (raw: unknown) => T): T[] {
  if (!Array.isArray(raw)) throw new DraftContractError("response_invalid")
  return raw.map(parser)
}


export function draftDate(raw: unknown): string {
  const value = draftString(raw)
  if (!/^\d{4}-\d{2}-\d{2}T/.test(value) ||
      !/(Z|[+-]\d{2}:\d{2})$/.test(value) ||
      !Number.isFinite(Date.parse(value))) throw new DraftContractError("response_date_invalid")
  return value
}

export const parseDraftUser = (raw: unknown): DraftUser => {
  const v = draftRecordFields(raw, ['user_id', 'username', 'role', 'enabled', 'credential_version'])
  return {user_id: draftUuid(draftString(v.user_id)), username: draftString(v.username), role: draftString(v.role), enabled: draftBoolean(v.enabled), credential_version: draftInteger(v.credential_version)}
}
export const parseDraftTeam = (raw: unknown): DraftTeam => {
  const v = draftRecordFields(raw, ['team_id', 'name', 'owner_user_id', 'version'])
  return {team_id: draftUuid(draftString(v.team_id)), name: draftString(v.name), owner_user_id: draftUuid(draftString(v.owner_user_id)), version: draftVersion(draftInteger(v.version))}
}
export const parseDraftMembership = (raw: unknown): DraftTeamMembership => {
  const v = draftRecordFields(raw, ['team_id', 'user_id', 'active'])
  return {team_id: draftUuid(draftString(v.team_id)), user_id: draftUuid(draftString(v.user_id)), active: draftBoolean(v.active)}
}
export const parseDraftProject = (raw: unknown): DraftProject => {
  const v = draftRecordFields(raw, ['project_id', 'name', 'owner_user_id', 'owner_team_id', 'version'])
  // A5 ProjectView owner fields default to null in OpenAPI, but XOR requires
  // EXACTLY one present. Missing both remains a hard contract violation.
  const owner_user_id = draftSourceDefault(v.owner_user_id,null,raw=>draftNullable(raw,x=>draftUuid(draftString(x))))
  const owner_team_id = draftSourceDefault(v.owner_team_id,null,raw=>draftNullable(raw,x=>draftUuid(draftString(x))))
  if (Boolean(owner_user_id) === Boolean(owner_team_id)) throw new DraftContractError("owner_xor_violation")
  return {project_id: draftUuid(draftString(v.project_id)), name: draftString(v.name), owner_user_id, owner_team_id, version: draftVersion(draftInteger(v.version))}
}
export const parseDraftAgent = (raw: unknown): DraftAgent => {
  const v = draftRecordFields(raw, ['agent_id', 'project_id', 'name', 'parent_agent_id', 'enabled', 'version'])
  return {agent_id: draftUuid(draftString(v.agent_id)), project_id: draftUuid(draftString(v.project_id)), name: draftString(v.name), parent_agent_id: draftNullable(v.parent_agent_id, x => draftUuid(draftString(x))), enabled: draftBoolean(v.enabled), version: draftVersion(draftInteger(v.version))}
}
export const parseDraftSession = (raw: unknown): DraftAgentSession => {
  const v = draftRecordFields(raw, ['session_uuid', 'project_id', 'grants', 'is_elevated', 'hard_expires_at', 'status', 'version', 'label', 'elevation_policy'])
  const session_uuid = draftSessionUuid(draftString(v.session_uuid))
  const hard_expires_at = draftString(v.hard_expires_at)
  if (!Number.isFinite(Date.parse(hard_expires_at))) throw new DraftContractError("session_expiry_invalid")
  const status = draftString(v.status)
  if (!["active", "expired", "revoked", "pending"].includes(status)) throw new DraftContractError("session_status_invalid")
  const elevation_policy=draftString(v.elevation_policy)
  if(elevation_policy!=="fixed"&&elevation_policy!=="requestable")throw new DraftContractError("session_policy_invalid")
  return {session_uuid, project_id: draftUuid(draftString(v.project_id)), grants: draftList(v.grants, draftString), is_elevated: draftBoolean(v.is_elevated), hard_expires_at, status, version: draftVersion(draftInteger(v.version)),label:draftSourceDefault(v.label,null,raw=>draftNullable(raw,draftString)),elevation_policy}
}
export const parseDraftPermissions = (raw: unknown): DraftPermissionView => {
  const v = draftRecordFields(raw, ['project_id', 'permissions'])
  return {project_id: draftUuid(draftString(v.project_id)), permissions: draftList(v.permissions, draftString)}
}
export const parseDraftInvitation = (raw: unknown): DraftInvitation => ({url: draftString(draftRecordFields(raw,["url"]).url)})
export const parseDraftApproval = (raw: unknown): DraftApproval => ({request_id: draftUuid(draftString(draftRecordFields(raw,["request_id"]).request_id))})
export const parseDraftToken = (raw: unknown): DraftAdminToken => {
  const v = draftRecordFields(raw, ['access_token', 'token_type', 'expires_at'])
  const token_type = draftString(v.token_type)
  const expires_at = draftString(v.expires_at)
  if (token_type !== "Bearer" || !Number.isFinite(Date.parse(expires_at)) || Date.parse(expires_at) <= Date.now()) throw new DraftContractError("token_invalid")
  const access_token = draftString(v.access_token)
  if (access_token.length < 40 || access_token.length > 8192 || /[\x00-\x20\x7f]/.test(access_token)) throw new DraftContractError("token_invalid")
  return {access_token, token_type, expires_at}
}
/** A5 read metadata is schema-scoped, never a credential/document dump. */
function publishedSettings(raw: unknown): Record<string, unknown> | null {
  if (raw===null) return null
  const record=draftRecordFields(raw,["base_url","display_name","installation_id","organization","namespace","tenant"])
  for (const [key,value] of Object.entries(record)) {
    if (key==="installation_id") {
      if (value!==null && (!Number.isSafeInteger(value) || typeof value!=="number" || value<=0))throw new DraftContractError("provider_metadata_invalid")
    } else {
      if (typeof value!=="string" || value.length>2048 || /[\x00-\x1f\x7f]/.test(value))throw new DraftContractError("provider_metadata_invalid")
      // Provider endpoints can appear directly in list/table/tooltip UI.
      // Never display an unreviewed URL containing basic-auth credentials,
      // query-string secrets, fragments or an untrusted local endpoint.
      if (key==="base_url" && value) {
        let endpoint:URL
        try {endpoint=new URL(value)}
        catch {throw new DraftContractError("provider_metadata_url_invalid")}
        const host=endpoint.hostname.toLowerCase()
        if(endpoint.protocol!=="https:"||!endpoint.hostname||endpoint.username||endpoint.password||
           endpoint.search||endpoint.hash||/[\s%]/.test(endpoint.host)||
           !["","443","8443"].includes(endpoint.port)||
           [".local",".localhost",".internal",".lan",".home",".onion"].some(suffix=>host.endsWith(suffix))){
          throw new DraftContractError("provider_metadata_url_invalid")
        }
      }
    }
  }
  return record
}
export const parseDraftResource = (raw: unknown): DraftResource => {
  const v = draftRecordFields(raw, ['resource_id', 'kind', 'name', 'version', 'project_access_revision', 'team_access_revision', 'owner_scope', 'owner_id', 'origin', 'inherited', 'is_secret', 'masked', 'provider', 'auth_type', 'display_name', 'provider_settings', 'credential_configured', 'connection_status', 'updated_at', 'value'])
  const kind = draftString(v.kind)
  const owner_scope = draftString(v.owner_scope)
  const origin = draftString(v.origin)
  if ((kind !== "variable" && kind !== "integration") || (owner_scope !== "team" && owner_scope !== "project") || origin !== owner_scope) throw new DraftContractError("resource_contract_invalid")
  const is_secret = draftBoolean(v.is_secret)
  const masked = draftBoolean(v.masked)
  const value = draftSourceDefault(v.value,null,(input)=>draftNullable(input,draftString))
  if (masked !== is_secret || (is_secret && value !== null)) throw new DraftContractError("credential_response_unmasked")
  if (kind === "integration" && (!is_secret || value !== null || !v.provider)) throw new DraftContractError("integration_secret_contract_invalid")
  if (draftBoolean(v.inherited) && owner_scope !== "team") throw new DraftContractError("inherited_owner_not_team")
  const sourceDecision = (value: unknown): string | null => {
    if (value === null || value === undefined) return null
    const decision = draftString(value)
    if (!/^[0-9a-f]{64}$/i.test(decision)) throw new DraftContractError("resource_decision_invalid")
    return decision.toLowerCase()
  }
  return {
    resource_id: draftUuid(draftString(v.resource_id)), kind, name: draftString(v.name), version: draftVersion(draftInteger(v.version)),
    project_access_revision:sourceDecision(v.project_access_revision),
    team_access_revision:sourceDecision(v.team_access_revision),
    owner_scope, owner_id: draftUuid(draftString(v.owner_id)), origin, inherited: draftBoolean(v.inherited),
    is_secret, masked,
    provider: draftSourceDefault(v.provider,null,(raw)=>draftNullable(raw,draftString)),
    auth_type: draftSourceDefault(v.auth_type,null,(raw)=>draftNullable(raw,draftString)),
    display_name: draftSourceDefault(v.display_name,"",draftString),
    provider_settings: draftSourceDefault(v.provider_settings,null,publishedSettings),
    credential_configured: draftSourceDefault(v.credential_configured,false,draftBoolean),
    connection_status: draftSourceDefault(v.connection_status,null,(raw)=>draftNullable(raw,draftString)),
    updated_at: draftSourceDefault(v.updated_at,null,(raw)=>draftNullable(raw,draftDate)),value,
  }
}
export const parseDraftRevoked = (raw: unknown): DraftResourceRevoked => {
  const v = draftRecordFields(raw, ['resource_id', 'revoked', 'new_version'])
  return {resource_id: draftUuid(draftString(v.resource_id)), revoked: draftBoolean(v.revoked), new_version: draftVersion(draftInteger(v.new_version))}
}
export const parseDraftChanged = (raw: unknown): { changed: boolean } => ({changed: draftBoolean(draftRecordFields(raw,["changed"]).changed)})
export const parseDraftRegistration = parseDraftUser
export const parseDraftLoggedOut = (raw: unknown): { revoked: boolean } => ({revoked: draftBoolean(draftRecordFields(raw,["revoked"]).revoked)})
