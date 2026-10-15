import {CONTROL_PANEL_API_V1} from "@/shared/config/control-panel-api"
import type {HandEffectScope} from "@/shared/lib/hand-effect-scope"
import {decodeFilesReadResult,isCanonicalFilesPath,MAX_FILES_READ_BYTES,type FilesReadDecode} from "../model/read-result"

/** A validated current owner projection, not a bearer or Cedar grant.
 * A caller must still have a freshly confirmed User, exact Project and
 * an owner-supplied PATH. Hash-only resource selectors are not reversible.
 * The BFF + Files Hand independently enforce every effect and revocation.
 */
export interface FilesReadSessionReference {
  project_uuid:string
  session_uuid:string
  revision:number
  status:"active"|"revoked"|"expired"
  hard_expires_at:string
  operations:readonly string[]
  resources:readonly HandEffectScope[]
}
export type FilesReadClientResult =
  | {kind:"ready";item:Extract<FilesReadDecode,{kind:"text"|"binary"}>}
  | {kind:"unauthorized"|"forbidden"|"invalid"|"unavailable"|"cancelled";code:string}

const UUID4=/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/
const DOMAIN=new TextEncoder().encode("files-project-relative-v1\0")
const LIMIT=384*1024

/** Compute only a local preflight equality check. This does not mint a
 * selector for the wire request: Backend computes and validates it again.
 */
async function ownerSelector(project:string,path:string):Promise<string>{
  const raw=new TextEncoder().encode(path)
  const source=new Uint8Array(DOMAIN.length+raw.length)
  source.set(DOMAIN);source.set(raw,DOMAIN.length)
  const digest=await crypto.subtle.digest("SHA-256",source)
  const sha=Array.from(new Uint8Array(digest),n=>n.toString(16).padStart(2,"0")).join("")
  return `project-path-v1:${project}:${sha}`
}

async function errorCode(reply:Response):Promise<string>{
  try{
    const data=await reply.json() as unknown
    if(data===null||typeof data!=="object"||Array.isArray(data))return "FILES_READ_UNAVAILABLE"
    const err=(data as Record<string,unknown>).error
    if(err===null||typeof err!=="object"||Array.isArray(err))return "FILES_READ_UNAVAILABLE"
    const code=(err as Record<string,unknown>).code
    return typeof code==="string"&&/^[A-Z][A-Z_]{0,80}$/.test(code)?code:"FILES_READ_UNAVAILABLE"
  }catch{return "FILES_READ_UNAVAILABLE"}
}

/** Strict maximum ~384 KiB JSON. No unbounded response.json() on a path that
 * can include up to 256 KiB of raw file content as canonical base64.
 */
async function boundedRead(reply:Response,signal:AbortSignal):Promise<unknown>{
  const size=reply.headers.get("content-length")
  if(size!==null&&(!/^\d{1,8}$/.test(size)||Number(size)>LIMIT))throw Error("untrusted file payload size")
  if(!reply.body)throw Error("missing body")
  const reader=reply.body.getReader()
  const chunks:Uint8Array[]=[],totalMax=LIMIT
  let total=0
  try{
    while(true){
      if(signal.aborted)throw Error("cancelled")
      const chunk=await reader.read()
      if(chunk.done)break
      total+=chunk.value.byteLength
      if(total>totalMax)throw Error("payload too large")
      chunks.push(chunk.value)
    }
  }catch(cause){
    // Do not keep buffering a maliciously oversized/aborted owner reply.
    await reader.cancel().catch(()=>{})
    throw cause
  }finally{reader.releaseLock()}
  if(signal.aborted)throw Error("cancelled")
  const bytes=new Uint8Array(total)
  let cursor=0
  for(const chunk of chunks){bytes.set(chunk,cursor);cursor+=chunk.length}
  return JSON.parse(new TextDecoder("utf-8",{fatal:true}).decode(bytes)) as unknown
}

/** Source-only transport: no application button can issue this request until
 * a trusted owner provides the canonical path for one exact current scope.
 * If the private Files owner is unmounted the BFF must return HTTP503.
 */
export async function readVerifiedFilesContent(
  source:FilesReadSessionReference,path:string,maxBytes:number,signal:AbortSignal,
):Promise<FilesReadClientResult>{
  if(signal.aborted)return {kind:"cancelled",code:"FILES_READ_CANCELLED"}
  const project=source.project_uuid,session=source.session_uuid,revision=source.revision
  if(!UUID4.test(project)||!UUID4.test(session)||source.status!=="active"||
    !Number.isSafeInteger(revision)||revision<1||
    !Number.isSafeInteger(maxBytes)||maxBytes<1||maxBytes>MAX_FILES_READ_BYTES||
    !isCanonicalFilesPath(path)||!source.operations.includes("files.read")||
    !Number.isFinite(Date.parse(source.hard_expires_at))||
    Date.parse(source.hard_expires_at)<=Date.now())return {kind:"invalid",code:"FILES_READ_SCOPE_INVALID"}
  if(typeof crypto==="undefined"||!crypto.subtle)return {kind:"unavailable",code:"FILES_READ_SECURE_CONTEXT_REQUIRED"}
  try{
    const selector=await ownerSelector(project,path)
    if(signal.aborted)return {kind:"cancelled",code:"FILES_READ_CANCELLED"}
    if(!source.resources.some(scope=>scope.hand==="files"&&scope.tool==="read_file"&&
      scope.action==="files.read"&&scope.resource.kind==="workspace_path"&&
      scope.resource.id===selector))return {kind:"invalid",code:"FILES_READ_SELECTOR_UNVERIFIED"}
    const response=await fetch(CONTROL_PANEL_API_V1+"/files/read",{
      method:"POST",credentials:"same-origin",mode:"same-origin",cache:"no-store",
      redirect:"error",referrerPolicy:"no-referrer",signal,
      headers:{Accept:"application/json","Content-Type":"application/json"},
      body:JSON.stringify({project_uuid:project,agent_session_uuid:session,
        expected_grant_revision:revision,path,max_bytes:maxBytes}),
    })
    if(signal.aborted)return {kind:"cancelled",code:"FILES_READ_CANCELLED"}
    if(response.status!==200){
      const code=await errorCode(response)
      return {kind:response.status===401?"unauthorized":response.status===403?"forbidden":
        response.status===422?"invalid":"unavailable",code}
    }
    if(response.headers.get("content-type")?.split(";",1)[0].trim()!=="application/json"){
      return {kind:"invalid",code:"FILES_READ_RESPONSE_MEDIA_INVALID"}
    }
    const payload=await boundedRead(response,signal)
    if(signal.aborted)return {kind:"cancelled",code:"FILES_READ_CANCELLED"}
    const decoded=await decodeFilesReadResult(payload,path,signal,maxBytes)
    if(decoded.kind==="text"||decoded.kind==="binary")return {kind:"ready",item:decoded}
    return {kind:decoded.kind==="cancelled"?"cancelled":decoded.kind==="unavailable"?"unavailable":"invalid",
      code:"FILES_READ_RESPONSE_NOT_VERIFIED"}
  }catch{return {kind:signal.aborted?"cancelled":"unavailable",code:signal.aborted?"FILES_READ_CANCELLED":"FILES_READ_UNAVAILABLE"}}
}
