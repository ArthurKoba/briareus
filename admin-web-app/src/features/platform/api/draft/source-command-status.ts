/** Accepted A5 unpublished command status GET: scope/actor checked by Backend. */
import { DraftContractError,draftRecordFields,draftString,draftBoolean,draftNullable,draftDate,draftUuid,draftInteger,draftSourceDefault } from "@/features/platform/api/draft/source-contract"
export type SourceCommandState="not_found"|"pending"|"completed"
export interface SourceCommandStatus {
  project_id:string;operation:string;state:SourceCommandState
  outcome_http_status:number|null;expires_at:string|null;reconciliation_required:boolean
}
export function parseSourceCommandStatus(raw:unknown):SourceCommandStatus {
  const v=draftRecordFields(raw,["project_id","operation","state","outcome_http_status","expires_at","reconciliation_required"])
  const operation=draftString(v.operation)
  if(!/^[A-Za-z][A-Za-z0-9_.:-]{0,127}$/.test(operation))throw new DraftContractError("command_operation_invalid")
  const state=draftString(v.state)
  if(!["not_found","pending","completed"].includes(state))throw new DraftContractError("command_state_unknown")
  const outcome_http_status=draftSourceDefault(v.outcome_http_status,null,raw=>draftNullable(raw,draftInteger))
  if(outcome_http_status!==null&&(outcome_http_status<100||outcome_http_status>599))throw new DraftContractError("command_outcome_invalid")
  const reconciliation_required=draftSourceDefault(v.reconciliation_required,true,draftBoolean)
  if((state==="completed"&&(reconciliation_required||outcome_http_status===null))||
    (state!=="completed"&&(!reconciliation_required||outcome_http_status!==null))) {
    throw new DraftContractError("command_status_conflicting")
  }
  return {project_id:draftUuid(draftString(v.project_id)),operation,state:state as SourceCommandState,
    outcome_http_status,expires_at:draftSourceDefault(v.expires_at,null,raw=>draftNullable(raw,draftDate)),reconciliation_required}
}


/** Accepted A6 separate Team, owner-created and existing-resource status DTO. */
export type SourceScopedCommandKind="team"|"project_resource"|"resource"
export interface SourceScopedCommandStatus {
  scope_kind:SourceScopedCommandKind;scope_id:string;operation:string;state:SourceCommandState
  outcome_http_status:number|null;expires_at:string|null;reconciliation_required:boolean
}
export function parseSourceScopedCommandStatus(raw:unknown):SourceScopedCommandStatus {
  const v=draftRecordFields(raw,["scope_kind","scope_id","operation","state","outcome_http_status","expires_at","reconciliation_required"])
  const scope_kind=draftString(v.scope_kind)
  if(!["team","project_resource","resource"].includes(scope_kind))throw new DraftContractError("scoped_status_kind_invalid")
  const operation=draftString(v.operation)
  if(!/^[A-Za-z][A-Za-z0-9_.:-]{0,127}$/.test(operation))throw new DraftContractError("scoped_status_operation_invalid")
  const state=draftString(v.state)
  if(!["not_found","pending","completed"].includes(state))throw new DraftContractError("scoped_status_state_invalid")
  const outcome_http_status=draftSourceDefault(v.outcome_http_status,null,x=>draftNullable(x,draftInteger))
  if(outcome_http_status!==null&&(outcome_http_status<100||outcome_http_status>599))throw new DraftContractError("scoped_status_http_invalid")
  const expires_at=draftSourceDefault(v.expires_at,null,x=>draftNullable(x,draftDate))
  const reconciliation_required=draftSourceDefault(v.reconciliation_required,true,draftBoolean)
  if((state==="completed"&&(reconciliation_required||outcome_http_status===null))||
     (state!=="completed"&&(!reconciliation_required||outcome_http_status!==null)))
    throw new DraftContractError("scoped_status_conflicting")
  return {scope_kind:scope_kind as SourceScopedCommandKind,scope_id:draftUuid(draftString(v.scope_id)),
    operation,state:state as SourceCommandState,outcome_http_status,expires_at,reconciliation_required}
}
