/** SOURCE-ONLY parity with Runtime files_hand/_read_adapter.py.
 * Validates returned bytes, NOT a User/Project grant or signed read receipt.
 * No route or transport is invented here; the future BFF owns authorization.
 */
export const MAX_FILES_READ_BYTES=262_144
export type FilesReadDecode=
  | {kind:"text";path:string;sizeBytes:number;sha256:string;content:string}
  | {kind:"binary";path:string;sizeBytes:number;sha256:string}
  | {kind:"invalid"|"unavailable"|"cancelled"}
const utf8=new TextEncoder()
export function isCanonicalFilesPath(path:unknown):path is string {
  if(typeof path!=="string"||!path||path.startsWith("/")||path.includes("\\")||
    /[\u0000-\u001f\u007f]/.test(path)||path.normalize("NFC")!==path)return false
  const bytes=utf8.encode(path),parts=path.split("/")
  return bytes.length<=4096&&new TextDecoder("utf-8",{ignoreBOM:true}).decode(bytes)===path&&parts.length<=64&&
    parts.every(part=>part!==""&&part!=="."&&part!==".."&&utf8.encode(part).length<=255&&
      !/^\.upload-[0-9a-f]{32}\.tmp$/.test(part))
}
export async function decodeFilesReadResult(
  value:unknown,
  expectedPath:string,
  signal?:AbortSignal,
  maxBytes=MAX_FILES_READ_BYTES,
):Promise<FilesReadDecode>{
  if(signal?.aborted)return {kind:"cancelled"}
  if(!isCanonicalFilesPath(expectedPath)||!Number.isSafeInteger(maxBytes)||maxBytes<1||maxBytes>MAX_FILES_READ_BYTES||
    !value||typeof value!=="object"||Array.isArray(value))return {kind:"invalid"}
  const result=value as Record<string,unknown>
  if(Object.keys(result).length!==4||
    Object.keys(result).some(key=>!["path","size_bytes","sha256","content_base64"].includes(key))||
    result.path!==expectedPath||!Number.isSafeInteger(result.size_bytes)||
    (result.size_bytes as number)<0||(result.size_bytes as number)>maxBytes||
    typeof result.sha256!=="string"||!/^[0-9a-f]{64}$/.test(result.sha256)||
    typeof result.content_base64!=="string"||
    result.content_base64.length!==4*Math.ceil((result.size_bytes as number)/3)||
    !/^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/.test(result.content_base64))return {kind:"invalid"}
  if(typeof crypto==="undefined"||!crypto.subtle)return {kind:"unavailable"}
  try{
    const binary=atob(result.content_base64)
    if(binary.length!==result.size_bytes||btoa(binary)!==result.content_base64)return {kind:"invalid"}
    const bytes=new Uint8Array(binary.length)
    for(let i=0;i<binary.length;i++)bytes[i]=binary.charCodeAt(i)
    const digest=await crypto.subtle.digest("SHA-256",bytes)
    if(signal?.aborted)return {kind:"cancelled"}
    const hash=Array.from(new Uint8Array(digest),byte=>byte.toString(16).padStart(2,"0")).join("")
    if(hash!==result.sha256)return {kind:"invalid"}
    const metadata={path:expectedPath,sizeBytes:binary.length,sha256:hash}
    try{
      const content=new TextDecoder("utf-8",{fatal:true,ignoreBOM:true}).decode(bytes)
      if(/[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]/.test(content))return {kind:"binary",...metadata}
      return {kind:"text",...metadata,content}
    }catch{return {kind:"binary",...metadata}}
  }catch{return {kind:"invalid"}}
}
