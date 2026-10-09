/**
 * ACCEPTED Backend A5 SOURCE-only authorization/_scoped_events.py feed.
 * There is deliberately NO WebSocket URL, token transport, subscribe or ACK
 * method here: A5 is an internal Python port, not an approved public protocol.
 * A raw header, User-supplied receipt or arbitrary feed frame grants nothing.
 */
import {
  DraftContractError,draftRecordFields,draftList,draftNullable,draftDate,
  draftString,draftInteger,draftSessionUuid,
} from "@/features/platform/api/draft/source-contract"
import type { ScopedEvent } from "@/features/platform/model/contracts"

export type FeedScopeKind="project"|"team"|"user"
export interface FeedScope {kind:FeedScopeKind;scope_id:string}
export interface FeedOffset {scope:FeedScope;epoch:string;after_sequence:number}
export interface FeedSubscription {
  subscriber_id:string;scope:FeedScope;actor_id:string;decision_version:string
  offsets:FeedOffset[];expires_at:string
}
export interface FeedEvent {
  event_id:string;source_outbox_id:string;scope:FeedScope;sequence:number;epoch:string
  event_type:string;actor_user_id:string|null
  payload:Record<string,string|number|boolean>;created_at:string
}
export interface FeedBatch {subscription:FeedSubscription;events:FeedEvent[];resume_offsets:FeedOffset[]}
export interface VerifiedFeedViewer {
  /** Caller *already* authenticated by accepted server, NEVER browser input. */
  actorId:string
  scope:FeedScope
  decisionVersion:string
  /** Validated Team ID of selected Team-owned Project, if any. */
  ownerTeamId?:string|null
}

const uuid4=(value:unknown)=>draftSessionUuid(draftString(value))
const revision=(value:unknown)=>{
  const text=draftString(value)
  if(!/^[a-f0-9]{64}$/i.test(text))throw new DraftContractError("feed_decision_invalid")
  return text.toLowerCase()
}
const natural=(value:unknown)=>{
  const n=draftInteger(value)
  if(n<0)throw new DraftContractError("feed_sequence_invalid")
  return n
}
const identifier=(value:unknown)=>{
  const text=draftString(value)
  if(!/^[A-Za-z][A-Za-z0-9_.:-]{0,127}$/.test(text))throw new DraftContractError("feed_event_type_invalid")
  return text
}
const kind=(value:unknown):FeedScopeKind=>{
  const text=draftString(value)
  if(text!=="project"&&text!=="team"&&text!=="user")throw new DraftContractError("feed_scope_invalid")
  return text
}
const parseScope=(raw:unknown):FeedScope=>{
  const v=draftRecordFields(raw,["kind","scope_id"])
  return {kind:kind(v.kind),scope_id:uuid4(v.scope_id)}
}
const scopeKey=(scope:FeedScope)=>`${scope.kind}:${scope.scope_id}`
const parseOffset=(raw:unknown):FeedOffset=>{
  const v=draftRecordFields(raw,["scope","epoch","after_sequence"])
  return {scope:parseScope(v.scope),epoch:uuid4(v.epoch),after_sequence:natural(v.after_sequence)}
}
const parseSubscription=(raw:unknown):FeedSubscription=>{
  const v=draftRecordFields(raw,["subscriber_id","scope","actor_id","decision_version","offsets","expires_at"])
  const offsets=draftList(v.offsets,parseOffset)
  if(!offsets.length||new Set(offsets.map(item=>scopeKey(item.scope))).size!==offsets.length)
    throw new DraftContractError("feed_offsets_invalid")
  return {subscriber_id:uuid4(v.subscriber_id),scope:parseScope(v.scope),actor_id:uuid4(v.actor_id),
    decision_version:revision(v.decision_version),offsets,expires_at:draftDate(v.expires_at)}
}
const PUBLIC_DETAIL_KEYS=new Set([
  "owner_scope","owner_id","team_id","new_owner_id","new_owner_user_id","new_owner_team_id",
  "old_owner_user_id","old_team_id","resource_id","resource_version","owner_resource_revision",
  "quota_revision","reservation_revision","runtime_revision","job_version","job_status",
  "native_import_version","native_project_id","source_file_version","source_file_object_id",
  "session_version","approved","artifact_confirmed","reconciliation_required","cleanup_required",
  "over_limit","object_id",
])
const parsePayload=(raw:unknown):Record<string,string|number|boolean>=>{
  const v=draftRecordFields(raw,[...PUBLIC_DETAIL_KEYS])
  const output:Record<string,string|number|boolean>={}
  for(const [key,value] of Object.entries(v)){
    if(typeof value==="boolean")output[key]=value
    else if(typeof value==="number"&&Number.isSafeInteger(value)&&value>=0)output[key]=value
    else if(typeof value==="string"&&/^[A-Za-z0-9_.:-]{1,128}$/.test(value))output[key]=value
    else throw new DraftContractError("feed_public_metadata_invalid")
  }
  return output
}
const parseEvent=(raw:unknown):FeedEvent=>{
  const v=draftRecordFields(raw,["event_id","source_outbox_id","scope","sequence","epoch","event_type","actor_user_id","payload","created_at"])
  return {event_id:uuid4(v.event_id),source_outbox_id:uuid4(v.source_outbox_id),
    scope:parseScope(v.scope),sequence:natural(v.sequence),epoch:uuid4(v.epoch),
    event_type:identifier(v.event_type),actor_user_id:draftNullable(v.actor_user_id,uuid4),
    payload:parsePayload(v.payload),created_at:draftDate(v.created_at)}
}
export function parseA5FeedBatch(raw:unknown):FeedBatch {
  const v=draftRecordFields(raw,["subscription","events","resume_offsets"])
  const subscription=parseSubscription(v.subscription)
  const events=draftList(v.events,parseEvent)
  const resume_offsets=draftList(v.resume_offsets,parseOffset)
  const rotated=new Map(subscription.offsets.map(item=>[scopeKey(item.scope),item]))
  const resumed=new Map(resume_offsets.map(item=>[scopeKey(item.scope),item]))
  // IMPORTANT: Accepted A5 ScopedEventFeed.poll() returns an ALREADY ROTATED
  // subscription (offsets=next_offsets), plus the same resume_offsets.
  // The original cursor is NOT present in a ScopeBatch response. A caller
  // must keep the prior verified cursor separately to detect cross-batch gaps.
  if(resume_offsets.length!==rotated.size||resumed.size!==rotated.size||
     resume_offsets.some(item=>{
       const next=rotated.get(scopeKey(item.scope))
       return !next||next.epoch!==item.epoch||next.after_sequence!==item.after_sequence
     }))throw new DraftContractError("feed_rotated_subscription_mismatch")
  const observedIds=new Set<string>()
  const observedSeq=new Set<string>()
  for(const item of events){
    const key=scopeKey(item.scope),last=resumed.get(key)
    // A5 sorts the final cross-scope batch by created_at. It intentionally
    // does NOT promise a total event ordering across independent scopes.
    if(!last||item.epoch!==last.epoch||item.sequence<1||item.sequence>last.after_sequence||
       observedSeq.has(`${key}:${item.sequence}`)||observedIds.has(item.event_id)){
      throw new DraftContractError("feed_epoch_sequence_mismatch")
    }
    observedSeq.add(`${key}:${item.sequence}`)
    observedIds.add(item.event_id)
  }
  return {subscription,events,resume_offsets}
}

/**
 * Memory-only stream cursor. A5 has 7-day server retention and 60-second
 * subscription TTL, but the browser holds NO durable receipt or ACK proof.
 * On epoch/actor/permission/revision or cursor mismatch it fails closed and
 * requires an authenticated new subscribe/snapshot handled by future C2.
 */
export class A5SourceFeedCursor {
  private last:FeedSubscription|null=null
  clear():void {this.last=null}
  /**
   * Called only with a fresh SERVER-VERIFIED subscription from the future
   * approved Gateway. No initial baseline => cannot detect a skipped first
   * batch, so ingest() never silently accepts an unseeded stream.
   */
  start(raw:unknown,viewer:VerifiedFeedViewer,now=Date.now()):void {
    const subscription=parseSubscription(raw)
    assertFeedViewer(subscription,viewer,now)
    this.clear()
    this.last=subscription
  }
  ingest(raw:unknown,viewer:VerifiedFeedViewer,now=Date.now()):ScopedEvent[] {
    const before=this.last
    if(!before)throw new DraftContractError("feed_verified_subscription_required")
    if(Date.parse(before.expires_at)<=now){
      this.clear()
      throw new DraftContractError("feed_subscription_expired_requires_resubscribe")
    }
    let batch:FeedBatch,events:ScopedEvent[]
    try {
      batch=parseA5FeedBatch(raw)
      events=mapVerifiedA5Events(batch,viewer,now)
    } catch(error) {
      this.clear()
      throw error
    }
    if(before){
      if(before.subscriber_id!==batch.subscription.subscriber_id||
         before.actor_id!==batch.subscription.actor_id||
         before.decision_version!==batch.subscription.decision_version||
         scopeKey(before.scope)!==scopeKey(batch.subscription.scope)){
        this.clear()
        throw new DraftContractError("feed_authority_or_subscriber_changed")
      }
      const prior=new Map(before.offsets.map(offset=>[scopeKey(offset.scope),offset]))
      if(prior.size!==batch.subscription.offsets.length){
        this.clear()
        throw new DraftContractError("feed_scope_set_changed")
      }
      for(const next of batch.resume_offsets){
        const last=prior.get(scopeKey(next.scope))
        if(!last||last.epoch!==next.epoch||next.after_sequence<last.after_sequence){
          this.clear()
          throw new DraftContractError("feed_cursor_epoch_changed")
        }
        const scoped=batch.events.filter(item=>scopeKey(item.scope)===scopeKey(next.scope))
          .sort((a,b)=>a.sequence-b.sequence)
        let previous=last.after_sequence
        for(const event of scoped){
          if(event.sequence!==previous+1){
            this.clear()
            throw new DraftContractError("feed_history_gap_requires_new_subscription")
          }
          previous=event.sequence
        }
        if(previous!==next.after_sequence){
          this.clear()
          throw new DraftContractError("feed_cursor_skipped_undelivered_events")
        }
      }
    }
    this.last=batch.subscription
    return events
  }
}

const SECURITY_CHANGES=new Set([
  "identity.suspended","identity.deleted","identity.role_changed","identity.password_changed","identity.password_reset",
  "team.member_removed","team.member_added","team.owner_transferred",
  "project.transferred_to_team","project.withdrawn_to_personal","project.admin_reassigned",
  "session.revoked","resource.integration.rotated","resource.integration.revoked",
  "resource.variable.rotated","resource.variable.revoked","runtime.session_revoked","runtime.session_expired",
])
/**
 * Pure downstream projector: input MUST already come from verified A5 feed
 * after approved future authenticated Gateway transport. Fail-closed if the
 * actor, authorization revision, subscribed scope, 60s TTL or epoch changed.
 * Epoch, sequence and cursor are PER SCOPE, never globally ordered/ACKed.
 */
function assertFeedViewer(sub:FeedSubscription,viewer:VerifiedFeedViewer,now:number):void {
  if(sub.actor_id!==uuid4(viewer.actorId)||scopeKey(sub.scope)!==scopeKey(viewer.scope)||
     sub.decision_version!==revision(viewer.decisionVersion)||Date.parse(sub.expires_at)<=now||
     Date.parse(sub.expires_at)>now+60_000+5_000)throw new DraftContractError("feed_verification_expired")
  const authorized=new Set(sub.offsets.map(o=>scopeKey(o.scope)))
  if(!authorized.has(scopeKey(viewer.scope)))throw new DraftContractError("feed_selected_scope_missing")
  if([...authorized].some(key=>key!==scopeKey(viewer.scope)&&!(viewer.ownerTeamId&&key===`team:${uuid4(viewer.ownerTeamId)}`)))
    throw new DraftContractError("feed_unauthorized_scope")
}

export function mapVerifiedA5Events(batch:FeedBatch, viewer:VerifiedFeedViewer, now=Date.now()):ScopedEvent[] {
  assertFeedViewer(batch.subscription,viewer,now)
  return batch.events.map(item=>{
    const addressed=item.scope.kind==="project"?{projectId:item.scope.scope_id,teamId:null}:
      item.scope.kind==="team"?{projectId:null,teamId:item.scope.scope_id}:
      {projectId:null,teamId:null}
    const security=SECURITY_CHANGES.has(item.event_type)
    const ownUser=item.scope.kind==="user"&&item.scope.scope_id===viewer.actorId
    const kind=ownUser&&security?"principal-revoked" as const:
      security?"permissions-changed" as const:"invalidate" as const
    // Everything else is an invalidation signal; no payload acts as a grant.
    const resource=item.event_type.startsWith("agent.")?"agents" as const:
      item.event_type.startsWith("session.")?"sessions" as const:
      item.event_type.startsWith("resource.integration.")?"accounts" as const:
      item.event_type.startsWith("resource.variable.")?"variables" as const:
      item.event_type.startsWith("team.")?"teams" as const:
      item.event_type.startsWith("project.")?"projects" as const:
      item.event_type.startsWith(("runtime."))?"operations" as const:"all" as const
    return {kind,resource,...addressed}
  })
}
