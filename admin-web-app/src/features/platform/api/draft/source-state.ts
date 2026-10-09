/** Accepted A5 unpublished ProjectOperationalState: database metadata ONLY. */
import {
  DraftContractError,draftRecordFields,draftString,draftBoolean,draftInteger,
  draftList,draftNullable,draftDate,draftUuid,draftSessionUuid,draftVersion,
} from "@/features/platform/api/draft/source-contract"

export interface SourceRuntimeSession {
  runtime_session_uuid:string;actor_user_id:string;agent_session_uuid:string
  kind:string;status:string;cleanup_state:string;version:number
  idle_expires_at:string;hard_expires_at:string;lease_expires_at:string
}
export interface SourceRuntimeJob {
  job_uuid:string;runtime_session_uuid:string;operation:string;status:string;version:number;hard_expires_at:string
}
export interface SourceFileQuota {
  byte_limit:number;used_bytes:number;reserved_bytes:number;frozen:boolean;version:number;file_count:number
}
export interface SourceNativeProject {native_project_id:string;enabled:boolean;version:number}
export interface SourceNativeImport {
  import_uuid:string;operation_uuid:string;native_project_id:string
  source_file_version:number;status:string;version:number;cleanup_state:string
}
export interface SourceProjectOperationalState {
  project_id:string;project_access_revision:string;observed_at:string;limit:number
  runtime_sessions:SourceRuntimeSession[];jobs:SourceRuntimeJob[];quota:SourceFileQuota|null
  native_projects:SourceNativeProject[];native_imports:SourceNativeImport[];note:string
}
const id=(value:unknown)=>draftUuid(draftString(value))
const session=(value:unknown)=>draftSessionUuid(draftString(value))
const status=(value:unknown)=>{
  const text=draftString(value)
  // A5 ledger statuses are open-ended strings; never interpret unknown as
  // confirmed process liveness, cleanup success or verified import.
  if(!text||text.length>128||/[\x00-\x1f\x7f]/.test(text))throw new DraftContractError("unsafe_ledger_metadata")
  return text
}
const count=(value:unknown)=>{
  const n=draftInteger(value)
  if(n<0)throw new DraftContractError("negative_ledger_quantity")
  return n
}
const hash=(value:unknown)=>{
  const raw=draftString(value)
  if(!/^[a-f0-9]{64}$/i.test(raw))throw new DraftContractError("project_access_revision_invalid")
  return raw.toLowerCase()
}
const parseRuntime=(raw:unknown):SourceRuntimeSession=>{
  const v=draftRecordFields(raw,["runtime_session_uuid","actor_user_id","agent_session_uuid","kind","status","cleanup_state","version","idle_expires_at","hard_expires_at","lease_expires_at"])
  return {
    runtime_session_uuid:session(v.runtime_session_uuid),actor_user_id:id(v.actor_user_id),agent_session_uuid:session(v.agent_session_uuid),
    kind:status(v.kind),status:status(v.status),cleanup_state:status(v.cleanup_state),version:draftVersion(v.version as number),
    idle_expires_at:draftDate(v.idle_expires_at),hard_expires_at:draftDate(v.hard_expires_at),lease_expires_at:draftDate(v.lease_expires_at),
  }
}
const parseJob=(raw:unknown):SourceRuntimeJob=>{
  const v=draftRecordFields(raw,["job_uuid","runtime_session_uuid","operation","status","version","hard_expires_at"])
  return {job_uuid:session(v.job_uuid),runtime_session_uuid:session(v.runtime_session_uuid),operation:status(v.operation),status:status(v.status),
    version:draftVersion(v.version as number),hard_expires_at:draftDate(v.hard_expires_at)}
}
const parseQuota=(raw:unknown):SourceFileQuota=>{
  const v=draftRecordFields(raw,["byte_limit","used_bytes","reserved_bytes","frozen","version","file_count"])
  return {byte_limit:count(v.byte_limit),used_bytes:count(v.used_bytes),reserved_bytes:count(v.reserved_bytes),frozen:draftBoolean(v.frozen),
    version:draftVersion(v.version as number),file_count:count(v.file_count)}
}
const parseNative=(raw:unknown):SourceNativeProject=>{
  const v=draftRecordFields(raw,["native_project_id","enabled","version"])
  return {native_project_id:id(v.native_project_id),enabled:draftBoolean(v.enabled),version:draftVersion(v.version as number)}
}
const parseImport=(raw:unknown):SourceNativeImport=>{
  const v=draftRecordFields(raw,["import_uuid","operation_uuid","native_project_id","source_file_version","status","version","cleanup_state"])
  return {import_uuid:session(v.import_uuid),operation_uuid:session(v.operation_uuid),native_project_id:id(v.native_project_id),
    source_file_version:draftVersion(v.source_file_version as number),status:status(v.status),version:draftVersion(v.version as number),cleanup_state:status(v.cleanup_state)}
}
export function parseSourceOperationalState(raw:unknown):SourceProjectOperationalState {
  const v=draftRecordFields(raw,["project_id","project_access_revision","observed_at","limit","runtime_sessions","jobs","quota","native_projects","native_imports","note"])
  const limit=count(v.limit)
  if(limit<1||limit>100)throw new DraftContractError("operational_limit_invalid")
  const runtime_sessions=draftList(v.runtime_sessions,parseRuntime)
  const jobs=draftList(v.jobs,parseJob)
  const native_projects=draftList(v.native_projects,parseNative)
  const native_imports=draftList(v.native_imports,parseImport)
  if([runtime_sessions,jobs,native_projects,native_imports].some(rows=>rows.length>limit))throw new DraftContractError("operational_list_exceeds_limit")
  const unique=<T>(items:T[], select:(item:T)=>string)=>new Set(items.map(select)).size===items.length
  if(!unique(runtime_sessions,r=>r.runtime_session_uuid)||!unique(jobs,r=>r.job_uuid)||
     !unique(native_projects,r=>r.native_project_id)||!unique(native_imports,r=>r.import_uuid)){
    throw new DraftContractError("operational_ids_duplicate")
  }
  // A5 default note is optional OpenAPI metadata, not a process-health proof.
  const note=v.note===undefined?"":draftString(v.note)
  if(note.length>512||/[\x00-\x1f\x7f]/.test(note))throw new DraftContractError("operational_note_invalid")
  return {
    project_id:id(v.project_id),project_access_revision:hash(v.project_access_revision),observed_at:draftDate(v.observed_at),limit,
    runtime_sessions,jobs,quota:draftNullable(v.quota,parseQuota),native_projects,native_imports,
    note,
  }
}
