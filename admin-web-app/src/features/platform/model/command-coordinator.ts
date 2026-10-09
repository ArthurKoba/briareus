import { reactive } from "vue"
import type { ScopeSelection, UiCapability, SourceCommandBinding, SourceCommandTarget } from "@/features/platform/model/contracts"

/**
 * In-memory command outcome fence shared across Project pages in ONE tab.
 * An AbortSignal stops the frontend wait, NOT an already accepted server write.
 * These entries deliberately never reach localStorage, a URL, telemetry or logs.
 * A durable cross-reload proof requires a server idempotency/status endpoint.
 */
export type CommandResource = "profile" | "invitations" | "users" | "teams" | "projects" | "agents" | "sessions" | "accounts" | "variables"
/**
 * Authoritative reads are *typed by the original effect domain*. A successful
 * unrelated GET must never release an uncertain mutation (e.g., refreshing
 * Projects cannot reconcile credential rotation or a pending invitation).
 * A matching GET only provides current state, NOT a transaction-status proof.
 */
export function resourceForAction(action: UiCapability): CommandResource | null {
  if (action === "profile.password") return "profile"
  if (action === "invitations.issue" || action === "invitations.revoke") return "invitations"
  if (action.startsWith("users.")) return "users"
  if (action.startsWith("teams.")) return "teams"
  if (action.startsWith("projects.")) return "projects"
  if (action.startsWith("agents.")) return "agents"
  if (action.startsWith("sessions.")) return "sessions"
  if (action.startsWith("accounts.")) return "accounts"
  if (action.startsWith("variables.")) return "variables"
  return null
}

/** Exact A5 Project idempotency operation vocabulary, not a UI label. */
const PROJECT_COMMANDS=new Set(["agent.create","session.open","project.transfer_owner","project.admin_reassign"])
const RESOURCE_CREATES=new Set(["integration.create","variable.create"])
const RESOURCE_EDITS=new Set(["integration.update","integration.rotate","integration.revoke",
 "variable.update","variable.rotate","variable.revoke"])
const scopedCommand=/^(?:agent\.(?:rename|state)|session\.(?:elevation|resolve|revoke)):(?:[0-9a-f]{8}-){1}[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i
function acceptedProjectOperation(value:string):boolean {
  return PROJECT_COMMANDS.has(value)||scopedCommand.test(value)
}
function checkedSourceBinding(scope:ScopeSelection,requested:string|SourceCommandBinding|null):SourceCommandBinding|null|false {
  if(requested===null)return null
  const selected:SourceCommandBinding=typeof requested==="string"?
    scope.kind==="project"?{operation:requested,target:{kind:"project",id:scope.projectId}}:
    {operation:requested,target:{kind:"project",id:""}}:requested
  const {operation,target}=selected
  if(!/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(target.id))return false
  if(target.kind==="project")return (
    (scope.kind==="project"&&scope.projectId===target.id&&acceptedProjectOperation(operation))||
    (scope.kind==="operator"&&["project.admin_reassign","project.transfer_owner"].includes(operation))
  )?selected:false
  if(target.kind==="project_resource")return scope.kind==="project"&&scope.projectId===target.id&&RESOURCE_CREATES.has(operation)?selected:false
  if(target.kind==="team")return (scope.kind==="team"||scope.kind==="project")&&RESOURCE_CREATES.has(operation)?selected:false
  if(target.kind==="resource"){
    if(!RESOURCE_EDITS.has(operation)||!(scope.kind==="team"||scope.kind==="project"))return false
    const owner=target.owner
    if(owner.kind==="team")return owner.teamId!==""?selected:false
    return scope.kind==="project"&&owner.projectId===scope.projectId?selected:false
  }
  return false
}
type CommandState = "pending" | "reconciliation-required"
export interface PendingCommand {
  readonly scopeKey: string
  readonly action: UiCapability
  readonly commandId: string
  readonly decisionVersion: string | null
  /** Exact immutable A5 idempotency operation, never derived from UI label. */
  readonly sourceOperation: string | null
  readonly sourceTarget: SourceCommandTarget | null
  readonly state: CommandState
}
const pending = reactive(new Map<string, PendingCommand>())
function scopeKey(principal: string, scope: ScopeSelection): string {
  switch (scope.kind) {
    case "team": return `${principal}:team:${scope.teamId}`
    case "project": return `${principal}:project:${scope.projectId}`
    case "operator": return `${principal}:operator`
    case "account": return `${principal}:account`
  }
}
function lookup(principal: string, scope: ScopeSelection | null): PendingCommand | null {
  if (!principal || !scope) return null
  const own=pending.get(scopeKey(principal, scope))
  if(own)return own
  // A Team-owned connection can be accessed from multiple Projects in the
  // same Team. Until the server exposes command-result lookup, a mutation
  // whose outcome is UNKNOWN must fence every scope for that principal.
  for(const entry of pending.values()){
    if(entry.scopeKey.startsWith(`${principal}:`))return entry
  }
  return null
}
function begin(principal: string, scope: ScopeSelection, action: UiCapability, decisionVersion: string | null, selector: string | SourceCommandBinding | null = null): PendingCommand | null {
  if (!principal) return null
  const binding=checkedSourceBinding(scope,selector)
  if(binding===false)return null
  const key = scopeKey(principal, scope)
  // Only one unfinished mutation is permitted in a scope. A confirmation
  // dialog or route remount must never mint a fresh idempotency key for it.
  if (lookup(principal, scope)) return null
  const entry: PendingCommand = {
    scopeKey: key, action, commandId: crypto.randomUUID(),
    decisionVersion,sourceOperation:binding?.operation??null,
    sourceTarget:binding?.target??null,state: "pending",
  }
  pending.set(key, entry)
  return entry
}
function confirm(entry: PendingCommand): void {
  if (pending.get(entry.scopeKey)?.commandId === entry.commandId) pending.delete(entry.scopeKey)
}
function uncertain(entry: PendingCommand): void {
  if (pending.get(entry.scopeKey)?.commandId === entry.commandId) {
    pending.set(entry.scopeKey, { ...entry, state: "reconciliation-required" })
  }
}
function reconcile(principal: string, scope: ScopeSelection, entry: PendingCommand, readResource: CommandResource): boolean {
  const key = scopeKey(principal, scope)
  if (key !== entry.scopeKey || pending.get(key)?.commandId !== entry.commandId ||
      resourceForAction(entry.action) !== readResource) return false
  if (pending.get(key)?.state !== "reconciliation-required") return false
  pending.delete(key)
  return true
}
/** Never inspect A5 command status using an entry from another actor/scope. */
function matches(entry:PendingCommand,principal:string,scope:ScopeSelection):boolean {
  return Boolean(principal&&entry.scopeKey===scopeKey(principal,scope))
}
/** Forget opaque identity references only when account authentication ends. */
function clearAll(): void { pending.clear() }

export const commandCoordinator = { begin, lookup, confirm, uncertain, reconcile, matches, clearAll }
