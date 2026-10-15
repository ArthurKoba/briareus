import {readBoundedJsonResponse,readBoundedErrorCode} from "@/shared/lib/bounded-json-response"
import {CONTROL_PANEL_API_V1} from "@/shared/config/control-panel-api"
/** LOCAL Backend source contract: _oidc_catalog.py GET /api/v1/catalog.
 * Exact nonsecret Resource owner metadata; credentials/variables values never
 * leave Catalog SQL or enter the browser. This is NOT an MCP effect grant.
 */
import type { VerifiedPlatformContext } from "@/features/platform/api/platform-current"

export type CatalogKind="integration"|"variable"
export interface CatalogSummary {
  resource_uuid:string
  kind:CatalogKind
  owner:{kind:"project"|"team";id:string}
  key:string
  version:number
}
export type CatalogMetadataResult=
  | {kind:"ready";items:CatalogSummary[]}
  | {kind:"unauthorized"|"forbidden"|"invalid"|"unavailable";code:string}

const UUID4=/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/
const KEY=/^[A-Za-z0-9_.-]{1,128}$/
export const CATALOG_PAGE_LIMIT=50
function isObject(value:unknown):value is Record<string,unknown>{
  return typeof value==="object"&&value!==null&&!Array.isArray(value)
}
function exactKeys(value:Record<string,unknown>,keys:readonly string[]):boolean {
  return Object.keys(value).length===keys.length &&
    keys.every(key=>Object.prototype.hasOwnProperty.call(value,key))
}
function validUuid(value:unknown):value is string{
  return typeof value==="string"&&UUID4.test(value)
}
function hasCurrentProject(
  context:VerifiedPlatformContext,
  project:string,
):boolean {
  return context.user.enabled===true &&
    Date.parse(context.expires_at)>Date.now() &&
    context.projects.some(item=>item.id===project && item.permissions.includes("use_resources"))
}
export function parseCatalogMetadata(
  data:unknown,
  project:string,
  kind:CatalogKind,
  context:VerifiedPlatformContext,
):CatalogSummary[]|null {
  if(!hasCurrentProject(context,project)||!isObject(data)||
    !exactKeys(data,["items"])||!Array.isArray(data.items)||data.items.length>CATALOG_PAGE_LIMIT)return null
  const projectProof=context.projects.find(item=>item.id===project)
  if(!projectProof)return null
  const seen=new Set<string>(),result:CatalogSummary[]=[]
  for(const value of data.items){
    if(!isObject(value)||!exactKeys(value,["resource_uuid","kind","owner","key","version"])||
      !validUuid(value.resource_uuid)||seen.has(value.resource_uuid)||
      value.kind!==kind||!isObject(value.owner)||!exactKeys(value.owner,["kind","id"])||
      (value.owner.kind!=="team"&&value.owner.kind!=="project")||
      !validUuid(value.owner.id)||
      typeof value.key!=="string"||!KEY.test(value.key)||
      !Number.isSafeInteger(value.version)||(value.version as number)<1)return null
    const owner=value.owner
    if(owner.kind==="project"&&owner.id!==project)return null
    if(owner.kind==="team"&&(
      projectProof.owner.kind!=="team"||
      projectProof.owner.id!==owner.id||
      !context.teams.some(team=>team.id===owner.id)
    ))return null
    seen.add(value.resource_uuid)
    result.push({
      resource_uuid:value.resource_uuid,
      kind,
      owner:{kind:owner.kind as "project"|"team",id:owner.id as string},
      key:value.key,
      version:value.version as number,
    })
  }
  return result
}
export async function readCurrentCatalog(
  project:string,
  kind:CatalogKind,
  context:VerifiedPlatformContext,
  signal:AbortSignal,
):Promise<CatalogMetadataResult> {
  if(!validUuid(project)||!(kind==="integration"||kind==="variable")||!hasCurrentProject(context,project))
    return {kind:"forbidden",code:"CATALOG_PROJECT_PERMISSION_DENIED"}
  if(signal.aborted)return {kind:"unavailable",code:"CATALOG_READ_CANCELLED"}
  try{
    const response=await fetch(
      CONTROL_PANEL_API_V1+"/catalog?project_uuid="+encodeURIComponent(project)+"&kind="+kind,
      {method:"GET",signal,credentials:"same-origin",mode:"same-origin",
        redirect:"error",referrerPolicy:"no-referrer",cache:"no-store",
        headers:{Accept:"application/json"}},
    )
    if(signal.aborted)return {kind:"unavailable",code:"CATALOG_READ_CANCELLED"}
    if(response.status!==200){
      const code=await readBoundedErrorCode(response,signal,"UNKNOWN")
      if(signal.aborted)return {kind:"unavailable",code:"CATALOG_READ_CANCELLED"}
      return {kind:response.status===401?"unauthorized":
        response.status===403?"forbidden":
        response.status===422?"invalid":"unavailable",code}
    }
    const value:unknown=await readBoundedJsonResponse(response,signal,65_536)
    if(signal.aborted)return {kind:"unavailable",code:"CATALOG_READ_CANCELLED"}
    const items=parseCatalogMetadata(value,project,kind,context)
    return items?{kind:"ready",items}:{kind:"invalid",code:"CATALOG_DTO_INVALID"}
  }catch{return {kind:"unavailable",code:signal.aborted?"CATALOG_READ_CANCELLED":"CATALOG_NETWORK_UNAVAILABLE"}}
}
