import { computed, onBeforeUnmount, reactive, shallowReactive, watch, watchEffect } from "vue"
import { projectContext } from "@/features/platform/model/project-context"
import { platformPort } from "@/features/platform/api/port"
import { normalizeUiError, type UiError } from "@/features/platform/model/errors"
import { scopedEvents } from "@/features/platform/model/project-events"
import { refreshAuthenticatedProjection } from "@/features/platform/model/refresh-identity"
import { commandCoordinator, resourceForAction, type CommandResource, type PendingCommand } from "@/features/platform/model/command-coordinator"
import type { CommandContext, PlatformPort, QueryContext, ScopeSelection, UiCapability, SourceCommandBinding } from "@/features/platform/model/contracts"

function verifiedDecisionVersion(scope: ScopeSelection): string | null {
  if(scope.kind==="project")return projectContext.state.projectDecisionVersions[scope.projectId]??null
  if(scope.kind==="team")return projectContext.state.teamDecisionVersions[scope.teamId]??null
  return null
}

/** Only an accepted typed backend read of the mutated resource counts as reconciliation. */
async function readActionDomain(port:PlatformPort, context:QueryContext, resource:CommandResource, principal:string):Promise<void>{
  switch(resource){
    case "profile": {
      const projection=await port.auth.refresh(context.signal)
      if(!projection || !projection.user.active || projection.user.userId!==principal)throw new Error("Authoritative principal read unavailable")
      return
    }
    case "invitations": {
      const snapshot=await port.users.invitations(context)
      if(!Array.isArray(snapshot.items))throw new Error("Authoritative invitations snapshot unavailable")
      return
    }
    case "users": {
      if(context.scope.kind!=="operator")throw new Error("Operator scope required for User reconciliation")
      const snapshot=await port.users.list(context)
      if(!Array.isArray(snapshot.items))throw new Error("Authoritative Users snapshot unavailable")
      return
    }
    case "teams": {
      const snapshot=await port.teams.list(context)
      if(!Array.isArray(snapshot.items))throw new Error("Authoritative Teams snapshot unavailable")
      return
    }
    case "projects": {
      const snapshot=await port.projects.list(context)
      if(!Array.isArray(snapshot.items))throw new Error("Authoritative Projects snapshot unavailable")
      return
    }
    case "agents": {
      if(context.scope.kind!=="project")throw new Error("Project required for Agent reconciliation")
      const snapshot=await port.agents.list(context)
      if(!Array.isArray(snapshot.items))throw new Error("Authoritative Agents snapshot unavailable")
      return
    }
    case "sessions": {
      if(context.scope.kind!=="project")throw new Error("Project required for Session reconciliation")
      const snapshot=await port.sessions.list(context)
      if(!Array.isArray(snapshot.sessions)||!Array.isArray(snapshot.requests))throw new Error("Authoritative Session snapshot unavailable")
      return
    }
    case "accounts": {
      if(context.scope.kind!=="project"&&context.scope.kind!=="team")throw new Error("Resource owner scope required")
      const snapshot=await port.accounts.list(context,{scope:"all"})
      if(!Array.isArray(snapshot.items))throw new Error("Authoritative connection snapshot unavailable")
      return
    }
    case "variables": {
      if(context.scope.kind!=="project"&&context.scope.kind!=="team")throw new Error("Resource owner scope required")
      const snapshot=await port.variables.list(context,{scope:"all"})
      if(!Array.isArray(snapshot.items))throw new Error("Authoritative Variable snapshot unavailable")
      return
    }
  }
}

/**
 * Only accepted A5 PROJECT-scoped commands have a queryable identity.
 * Never ask this route about global, Team, personal-create or User commands.
 * A 404/not_found/pending/4xx is an unresolved effect, NOT rollback proof.
 */
async function confirmedProjectEffect(port:PlatformPort,context:QueryContext,entry:PendingCommand):Promise<boolean>{
  // A5 command status exists ONLY for Project-owned operations. Refreshing a
  // Team/global list is NOT a proof that an already-sent write did not commit.
  if(!entry.sourceOperation||!entry.sourceTarget||!port.commandStatus)return false
  const status=await port.commandStatus.get(context,{
    operation:entry.sourceOperation,idempotencyKey:entry.commandId,target:entry.sourceTarget,
  })
  return status.kind===entry.sourceTarget.kind&&status.id===entry.sourceTarget.id&&
    status.operation===entry.sourceOperation&&
    status.state==="completed"&&!status.reconciliationRequired&&
    status.outcomeHttpStatus!==null&&status.outcomeHttpStatus>=200&&status.outcomeHttpStatus<300
}

export interface DomainLoad<T> {
  items:T[]; revision?:string|null; serverLimit?:number; possiblyTruncated?:boolean; observedAt?:string
  nextAfterId?:string|null; hasMore?:boolean; pageSize?:number
}
export type ReadDomain<T> = (port: PlatformPort, context: QueryContext, after?:string|null) => Promise<DomainLoad<T>>
export type WriteDomain = (port: PlatformPort, context: CommandContext) => Promise<unknown>
export type LoadStatus = "blocked" | "idle" | "loading" | "ready" | "empty" | "error"

function sameScope(expected: ScopeSelection, revision: number): boolean {
  const selected = projectContext.selection()
  if (revision !== projectContext.state.revision || !selected || selected.kind !== expected.kind) return false
  if (selected.kind === "project") return expected.kind === "project" && selected.projectId === expected.projectId
  if (selected.kind === "team") return expected.kind === "team" && selected.teamId === expected.teamId
  return true
}
function requiresReconciliation(error: UiError): boolean {
  // No automatic replay with a fresh idempotency key after an uncertain write.
  // 409 may represent a stale version, collision, or still-running command.
  return error.kind === "uncertain" || error.kind === "conflict" || error.kind === "unknown"
}
function handlePermissionError(error: UiError, scope: ScopeSelection): boolean {
  if (error.kind === "unauthorized") { projectContext.clear(); return true }
  if (error.kind === "forbidden") {
    // Never retain stale Team/Project/operator actions after 403 or a
    // decision-version drift. A fresh AUTHENTICATED projection is necessary.
    projectContext.selectNone()
    void refreshAuthenticatedProjection()
    return true
  }
  return false
}

/** Reads and mutations have INDEPENDENT generations: a WS read must not erase an acknowledged write. */
export function useDomain<T>(
  resource: string,
  ability: UiCapability,
  read: ReadDomain<T>,
  scopes: ScopeSelection["kind"][] = ["account", "team", "project", "operator"],
  available: (port: PlatformPort) => boolean = () => true,
) {
  const state = shallowReactive({
    items: [] as T[],
    status: "blocked" as LoadStatus,
    revision: null as string | null,
    serverLimit: null as number | null,
    possiblyTruncated: false,
    observedAt: null as string | null,
    nextAfterId: null as string | null,
    hasMore: false,
    pageSize: null as number | null,
    loadingMore: false,
    loadMoreError: null as UiError | null,
    error: null as UiError | null,
    busy: false,
    actionError: null as UiError | null,
    reconciliationRequired: false,
    reconciliationNotice: false,
  })
  let readRun = 0
  let writeRun = 0
  let controller: AbortController | null = null
  let pagination: AbortController | null = null
  let mutation: AbortController | null = null
  let activeWrite: PendingCommand | null = null
  let disposed = false

  function usable(): boolean {
    const scope = projectContext.selection()
    const port = platformPort.value
    return Boolean(port && available(port) && scope && scopes.includes(scope.kind) && projectContext.can(ability))
  }
  function invalidate(): void {
    ++readRun
    ++writeRun
    controller?.abort()
    pagination?.abort()
    pagination=null
    // A discarded in-flight response is an UNKNOWN server write outcome.
    if (activeWrite) commandCoordinator.uncertain(activeWrite)
    activeWrite = null
    mutation?.abort()
    controller = null
    mutation = null
    state.items = []
    state.revision = null
    state.serverLimit = null
    state.possiblyTruncated = false
    state.observedAt = null
    state.nextAfterId=null
    state.hasMore=false
    state.pageSize=null
    state.loadingMore=false
    state.loadMoreError=null
    state.error = null
    state.actionError = null
    state.reconciliationRequired = false
    state.reconciliationNotice = false
    state.busy = false
    state.status = "blocked"
  }
  function snapshot(signal: AbortSignal): QueryContext | null {
    const scope = projectContext.selection()
    return scope ? {
      scope,signal,revision:projectContext.state.revision,
      decisionVersion:verifiedDecisionVersion(scope),
    } : null
  }
  async function reload(): Promise<boolean> {
    ++readRun
    controller?.abort()
    pagination?.abort()
    pagination=null
    state.loadingMore=false
    state.loadMoreError=null
    state.nextAfterId=null
    state.hasMore=false
    state.pageSize=null
    controller = null
    state.error = null
    state.items = []
    state.revision = null
    state.serverLimit = null
    state.possiblyTruncated = false
    state.observedAt = null
    if (!usable() || disposed) { state.status = "blocked"; return false }
    const port = platformPort.value
    if (!port) { state.status = "blocked"; return false }
    const generation = readRun
    const abort = new AbortController()
    controller = abort
    const context = snapshot(abort.signal)
    if (!context) { state.status = "blocked"; return false }
    state.status = "loading"
    try {
      const result = await read(port, context)
      if (disposed || generation !== readRun || abort.signal.aborted || !sameScope(context.scope, context.revision) || port !== platformPort.value) return false
      state.items = result.items
      state.revision = result.revision ?? null
      state.serverLimit = result.serverLimit ?? null
      state.possiblyTruncated = result.possiblyTruncated === true
      state.observedAt = result.observedAt ?? null
      state.nextAfterId=result.nextAfterId??null
      state.hasMore=result.hasMore===true
      state.pageSize=result.pageSize??null
      state.status = result.items.length ? "ready" : "empty"
      return true
    } catch (cause) {
      if (disposed || generation !== readRun || abort.signal.aborted || !sameScope(context.scope, context.revision)) return false
      const normalized = normalizeUiError(cause)
      if (handlePermissionError(normalized, context.scope)) return false
      state.error = normalized
      state.status = "error"
      return false
    } finally {
      if (controller === abort) controller = null
    }
  }
  /** One bounded A6 keyset GET, never a background auto-fetch or fake snapshot. */
  async function loadMore():Promise<boolean> {
    if(disposed||!usable()||!state.hasMore||!state.nextAfterId||state.loadingMore||
       state.status==="loading"||state.busy)return false
    const port=platformPort.value
    if(!port)return false
    const cursor=state.nextAfterId
    const version=readRun
    const abort=new AbortController()
    pagination=abort
    const context=snapshot(abort.signal)
    if(!context)return false
    state.loadingMore=true
    state.loadMoreError=null
    try {
      const result=await read(port,context,cursor)
      if(disposed||abort.signal.aborted||version!==readRun||
         !sameScope(context.scope,context.revision)||port!==platformPort.value)return false
      if(result.hasMore===true&&(!result.nextAfterId||result.nextAfterId===cursor)){
        throw new Error("A6 keyset cursor failed to advance")
      }
      // Page N is authorized independently; it is not an immutable snapshot.
      // Entity action confirmations are cleared by the caller's list watcher
      // if server authority changes; no newer Project/User is auto-selected.
      state.items=[...state.items,...result.items]
      state.nextAfterId=result.nextAfterId??null
      state.hasMore=result.hasMore===true
      state.pageSize=result.pageSize??state.pageSize
      state.status=state.items.length?"ready":"empty"
      return true
    }catch(error){
      if(!disposed&&!abort.signal.aborted&&version===readRun&&sameScope(context.scope,context.revision)){
        const issue=normalizeUiError(error)
        if(!handlePermissionError(issue,context.scope))state.loadMoreError=issue
      }
      return false
    }finally{
      if(pagination===abort){pagination=null;state.loadingMore=false}
    }
  }
  async function execute(action: UiCapability, write: WriteDomain, sourceOperation: string | SourceCommandBinding | null = null): Promise<boolean> {
    const port = platformPort.value
    if (!usable() || !projectContext.can(action) || state.busy || state.reconciliationRequired || !port || disposed ||
        commandCoordinator.lookup(projectContext.state.user?.key ?? "", projectContext.selection())) return false
    const generation = ++writeRun
    const abort = new AbortController()
    mutation = abort
    const base = snapshot(abort.signal)
    if (!base) return false
    const principal = projectContext.state.user?.key ?? ""
    const pending = commandCoordinator.begin(principal, base.scope, action, base.decisionVersion ?? null, sourceOperation)
    if (!pending) return false
    activeWrite = pending
    const context: CommandContext = { ...base, idempotencyKey: pending.commandId }
    state.busy = true
    state.actionError = null
    state.reconciliationNotice = false
    try {
      await write(port, context)
      if (disposed || generation !== writeRun || abort.signal.aborted || !sameScope(base.scope, base.revision) || port !== platformPort.value) {
        commandCoordinator.uncertain(pending)
        if(activeWrite===pending)activeWrite=null
        return false
      }
      commandCoordinator.confirm(pending)
      if (activeWrite === pending) activeWrite = null
      // A successful write is acknowledged independently of any subsequent read.
      // Failed refresh remains visible in state.status/error, never a fake write failure.
      await reload()
      return !disposed && generation === writeRun && sameScope(base.scope, base.revision)
    } catch (cause) {
      // The request may have reached the server even when its component was
      // unmounted, aborted or its response failed validation.
      const known = normalizeUiError(cause, "mutation")
      if (requiresReconciliation(known) || abort.signal.aborted) commandCoordinator.uncertain(pending)
      else commandCoordinator.confirm(pending)
      if (activeWrite === pending) activeWrite = null
      if (!disposed && !abort.signal.aborted && generation === writeRun && sameScope(base.scope, base.revision)) {
        const normalized = normalizeUiError(cause, "mutation")
        if (!handlePermissionError(normalized, base.scope)) {
          state.actionError = normalized
          state.reconciliationRequired = requiresReconciliation(normalized)
        }
      }
      return false
    } finally {
      if (mutation === abort) { state.busy = false; mutation = null }
    }
  }
  /** Verify A5 outcome (when Project-owned), THEN read authoritative effect domain. */
  async function reconcile():Promise<boolean> {
    if(state.busy||disposed)return false
    const scope=projectContext.selection()
    const principal=projectContext.state.user?.key??""
    const port=platformPort.value
    const entry=commandCoordinator.lookup(principal,scope)
    if(entry&&!scope)return false
    if(entry&&scope&&!commandCoordinator.matches(entry,principal,scope)){
      state.actionError={kind:"uncertain",code:"reconcile_scope_mismatch",message:"reconcileOriginalScope"}
      return false
    }
    if(entry&&resourceForAction(entry.action)!==resource){
      state.actionError={kind:"uncertain",code:"reconcile_domain_mismatch",message:"reconcileOriginalDomain"}
      return false
    }
    if(!scope||!port)return false
    const revision=projectContext.state.revision
    const abort=new AbortController()
    const stop=projectContext.onTransition(()=>abort.abort())
    const off=watch(platformPort,()=>abort.abort())
    try {
      const context:QueryContext={scope,signal:abort.signal,revision,decisionVersion:verifiedDecisionVersion(scope)}
      if(entry){
        if(!await confirmedProjectEffect(port,context,entry)){
          state.actionError=entry.sourceOperation?
            {kind:"uncertain",code:"command_not_confirmed",message:"commandStatusUnresolved"}:
            {kind:"unavailable",code:"no_global_status_contract",message:"serverCommandStatusRequired"}
          return false
        }
        await readActionDomain(port,context,resource as CommandResource,principal)
      }
      if(abort.signal.aborted||!sameScope(scope,revision)||port!==platformPort.value||principal!==projectContext.state.user?.key)return false
      const fresh=await reload()
      if(!fresh||disposed||abort.signal.aborted||!sameScope(scope,revision)||port!==platformPort.value)return false
      if(entry&&!commandCoordinator.reconcile(principal,scope,entry,resource as CommandResource)){
        state.actionError={kind:"uncertain",code:"reconcile_scope_mismatch",message:"reconcileOriginalScope"}
        return false
      }
      state.reconciliationRequired=false
      state.actionError=null
      state.reconciliationNotice=Boolean(entry)
      return true
    }catch(cause){
      if(!disposed&&!abort.signal.aborted&&sameScope(scope,revision)){
        const issue=normalizeUiError(cause)
        if(!handlePermissionError(issue,scope)){
          state.actionError=issue.kind==="unknown"?{kind:"unavailable",code:"source_reconciliation_failed",message:"reconcileReadFailed"}:issue
        }
      }
      return false
    }finally{stop();off();abort.abort()}
  }

  const stop = watch(() => [projectContext.state.revision, platformPort.value] as const, () => {
    invalidate()
    if (usable()) void reload()
  }, { immediate: true })
  const unsubscribe = scopedEvents.subscribe(event => {
    if (event.resource === resource || event.resource === "all") void reload()
  })
  onBeforeUnmount(() => { disposed = true; stop(); unsubscribe(); invalidate() })
  return { state, reload, loadMore, execute, reconcile, usable }
}

/** Standalone mutation needs a verified list-read to unlock uncertain results. */
export function useCommand(scopes: ScopeSelection["kind"][] = ["account", "team", "project", "operator"]) {
  const state = reactive({ busy: false, error: null as UiError | null, reconciliationRequired: false, reconciliationNotice: false })
  let active: AbortController | null = null
  let nonce = 0
  let disposed = false
  const currentEntry = computed(() => commandCoordinator.lookup(
    projectContext.state.user?.key ?? "", projectContext.selection(),
  ))
  const stopBarrier = watchEffect(() => {
    const blocked = currentEntry.value !== null
    const unconfirmed = currentEntry.value?.state === "reconciliation-required"
    state.reconciliationRequired = blocked
    if (unconfirmed && !state.error) {
      state.error = { kind: "uncertain", code: "command_outcome_pending", message: "outcomeUncertain" }
    }
    if (!blocked && state.error?.code === "command_outcome_pending") state.error = null
  })
  let commandInFlight: PendingCommand | null = null
  function invalidate(): void {
    ++nonce
    if (commandInFlight) commandCoordinator.uncertain(commandInFlight)
    commandInFlight = null
    active?.abort()
    active = null
    state.busy = false
    state.error = null
    state.reconciliationRequired = false
    state.reconciliationNotice = false
  }
  const stop = projectContext.onTransition(invalidate)
  const stopAdapter = watch(platformPort, invalidate)
  async function submit(ability: UiCapability, action: WriteDomain, sourceOperation: string | SourceCommandBinding | null = null): Promise<boolean> {
    const port = platformPort.value
    const scope = projectContext.selection()
    if (disposed || state.busy || state.reconciliationRequired || !port || !scope || !scopes.includes(scope.kind) || !projectContext.can(ability)) return false
    const actor = projectContext.state.user?.key ?? ""
    const generation = ++nonce
    const abort = new AbortController()
    const revision = projectContext.state.revision
    const pending = commandCoordinator.begin(actor, scope, ability, verifiedDecisionVersion(scope), sourceOperation)
    if (!pending) return false
    active = abort
    commandInFlight = pending
    state.busy = true
    state.error = null
    state.reconciliationNotice = false
    try {
      await action(port, {
        scope,revision,signal:abort.signal,idempotencyKey:pending.commandId,
        decisionVersion:pending.decisionVersion,
      })
      if(disposed || abort.signal.aborted || nonce !== generation || !sameScope(scope,revision) || platformPort.value!==port){
        commandCoordinator.uncertain(pending)
        if(commandInFlight===pending)commandInFlight=null
        return false
      }
      commandCoordinator.confirm(pending)
      commandInFlight = null
      return true
    } catch (cause) {
      const normalized = normalizeUiError(cause, "mutation")
      if (requiresReconciliation(normalized) || abort.signal.aborted || disposed || nonce !== generation) {
        commandCoordinator.uncertain(pending)
      } else {
        commandCoordinator.confirm(pending)
      }
      if (commandInFlight === pending) commandInFlight = null
      if (!disposed && !abort.signal.aborted && nonce === generation && sameScope(scope, revision) && platformPort.value === port) {
        const normalized = normalizeUiError(cause, "mutation")
        if (!handlePermissionError(normalized, scope)) {
          state.error = normalized
          state.reconciliationRequired = requiresReconciliation(normalized)
        }
      }
      return false
    } finally {
      if (active === abort) { state.busy = false; active = null }
    }
  }
  async function reconcile(): Promise<boolean> {
    if(disposed||state.busy)return false
    const context=projectContext.selection()
    const revision=projectContext.state.revision
    const port=platformPort.value
    const principal=projectContext.state.user?.key??""
    const entry=commandCoordinator.lookup(principal,context)
    if(!context||!port||!entry)return false
    const resource=resourceForAction(entry.action)
    if(!commandCoordinator.matches(entry,principal,context)){
      state.error={kind:"uncertain",code:"reconcile_scope_mismatch",message:"reconcileOriginalScope"}
      return false
    }
    if(!resource){
      state.error={kind:"unavailable",code:"command_status_required",message:"serverCommandStatusRequired"}
      return false
    }
    const abort=new AbortController()
    const off=projectContext.onTransition(()=>abort.abort())
    const unwatch=watch(platformPort,()=>abort.abort())
    try {
      // A5 Project command status is authoritative for ORIGINAL actor, scope,
      // operation and Idempotency-Key. A cached GET or a server `not_found`
      // never proves absence of an external side effect.
      if(!await confirmedProjectEffect(port,{
        scope:context,signal:abort.signal,revision,decisionVersion:verifiedDecisionVersion(context),
      },entry)){
        state.error=entry.sourceOperation?
          {kind:"uncertain",code:"command_not_confirmed",message:"commandStatusUnresolved"}:
          {kind:"unavailable",code:"no_global_status_contract",message:"serverCommandStatusRequired"}
        return false
      }
      await readActionDomain(port,{
        scope:context,signal:abort.signal,revision,
        decisionVersion:verifiedDecisionVersion(context),
      },resource,principal)
      if(disposed||abort.signal.aborted||!sameScope(context,revision)||port!==platformPort.value ||
         principal!==projectContext.state.user?.key)return false
      if(!commandCoordinator.reconcile(principal,context,entry,resource)){
        state.error={kind:"uncertain",code:"reconcile_scope_mismatch",message:"reconcileOriginalScope"}
        return false
      }
      state.error=null
      state.reconciliationRequired=false
      state.reconciliationNotice=true
      return true
    } catch(cause) {
      if(!disposed&&!abort.signal.aborted&&sameScope(context,revision)){
        const normalized=normalizeUiError(cause)
        state.error=normalized.kind==="unknown" ?
          {kind:"unavailable",code:"source_reconciliation_failed",message:"reconcileReadFailed"}:normalized
        if(normalized.kind==="unauthorized"||normalized.kind==="forbidden")handlePermissionError(normalized,context)
      }
      return false
    } finally {
      off()
      unwatch()
      abort.abort()
    }
  }
  onBeforeUnmount(() => { disposed = true; stop(); stopAdapter(); invalidate() })
  return { state, submit, reconcile }
}
