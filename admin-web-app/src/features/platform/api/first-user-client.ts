/** First-User-only same-origin wire. Not a privileged PlatformPort. */
import { canonicalUuid4 } from "@/features/platform/model/contracts"

const ROUTES=Object.freeze({
  register:"/api/auth/register",
  login:"/api/auth/login",
  logout:"/api/auth/logout",
  current:"/api/platform/me",
} as const)
const MAX_RESULT_BYTES=32768
const MAX_BEARER_LENGTH=8192
const MAX_BEARER_AGE_MS=15*60*1000

export type FirstUserError="invalid"|"rate_limited"|"unavailable"|"unauthorized"|"uncertain"
export class FirstUserWireError extends Error {
  constructor(readonly kind:FirstUserError){super(kind);this.name="FirstUserWireError"}
}
export interface VerifiedFirstUser {
  userId:string
  credentialVersion:number
}
interface LoginReceipt {token:string;expiresAt:number}
function record(raw:unknown):Record<string,unknown>{
  if(!raw||typeof raw!=="object"||Array.isArray(raw))throw new FirstUserWireError("unavailable")
  return raw as Record<string,unknown>
}
function fields(raw:Record<string,unknown>,keys:readonly string[]):void {
  if(Object.keys(raw).some(k=>!keys.includes(k))||keys.some(k=>!(k in raw)))
    throw new FirstUserWireError("unavailable")
}
function parseLogin(raw:unknown):LoginReceipt {
  const dto=record(raw)
  fields(dto,["access_token","token_type","expires_at"])
  if(dto.token_type!=="Bearer"||typeof dto.access_token!=="string"||
    dto.access_token.length<40||dto.access_token.length>MAX_BEARER_LENGTH||
    /\s/.test(dto.access_token)||typeof dto.expires_at!=="string"||
    !/(?:Z|[+-]\d{2}:\d{2})$/.test(dto.expires_at))throw new FirstUserWireError("unavailable")
  const expiresAt=Date.parse(dto.expires_at)
  if(!Number.isFinite(expiresAt)||expiresAt<=Date.now()||
    expiresAt>Date.now()+MAX_BEARER_AGE_MS+5000)throw new FirstUserWireError("unavailable")
  return {token:dto.access_token,expiresAt}
}
function parseCurrent(raw:unknown):VerifiedFirstUser {
  const dto=record(raw)
  fields(dto,["user_id","credential_version","source"])
  if(typeof dto.user_id!=="string"||!canonicalUuid4(dto.user_id)||
    !Number.isSafeInteger(dto.credential_version)||Number(dto.credential_version)<1||
    dto.source!=="verified-admin-bearer")throw new FirstUserWireError("unavailable")
  return {userId:dto.user_id,credentialVersion:Number(dto.credential_version)}
}
async function boundedJson(response:Response):Promise<unknown>{
  const header=response.headers.get("content-length")
  if(header!==null&&(!/^\d+$/.test(header)||Number(header)>MAX_RESULT_BYTES))
    throw new FirstUserWireError("unavailable")
  if(!response.body)throw new FirstUserWireError("unavailable")
  const reader=response.body.getReader()
  const parts:Uint8Array[]=[]
  let size=0
  try{
    for(;;){
      const {done,value}=await reader.read()
      if(done)break
      size+=value.byteLength
      if(size>MAX_RESULT_BYTES)throw new FirstUserWireError("unavailable")
      parts.push(value)
    }
  }finally{reader.releaseLock()}
  const bytes=new Uint8Array(size)
  let offset=0
  for(const part of parts){bytes.set(part,offset);offset+=part.byteLength}
  try{return JSON.parse(new TextDecoder("utf-8",{fatal:true}).decode(bytes)) as unknown}
  catch{throw new FirstUserWireError("unavailable")}
}
function classify(status:number):FirstUserError {
  if(status===401)return "unauthorized"
  if(status===429)return "rate_limited"
  if(status===403||status===400||status===422)return "invalid"
  return "unavailable"
}
async function sameOrigin(path:string,method:"GET"|"POST",signal:AbortSignal,body?:string,bearer?:string,original?:string):Promise<Response>{
  const headers:Record<string,string>={Accept:"application/json"}
  if(body!==undefined)headers["Content-Type"]="application/json"
  if(bearer!==undefined)headers.Authorization=`Bearer ${bearer}`
  if(original!==undefined){headers["Operation-UUID"]=original;headers["Idempotency-Key"]=original}
  return fetch(path,{
    method,signal,headers,body,credentials:"omit",cache:"no-store",
    redirect:"error",referrerPolicy:"no-referrer",mode:"same-origin",
  })
}
/** The bearer never leaves this module except in the outbound Authorization header. */
export function createFirstUserClient(){
  let token:string|null=null
  let expiresAt=0
  let epoch=0
  function invalidate(){++epoch;token=null;expiresAt=0}
  async function current(signal:AbortSignal):Promise<VerifiedFirstUser>{
    if(!token||Date.now()>=expiresAt){invalidate();throw new FirstUserWireError("unauthorized")}
    const generation=epoch
    let response:Response
    try{response=await sameOrigin(ROUTES.current,"GET",signal,undefined,token)}
    catch{invalidate();throw new FirstUserWireError("unavailable")}
    if(response.status===401||response.status===403){invalidate();throw new FirstUserWireError("unauthorized")}
    if(!response.ok)throw new FirstUserWireError(classify(response.status))
    const result=parseCurrent(await boundedJson(response))
    if(epoch!==generation||signal.aborted||Date.now()>=expiresAt){invalidate();throw new FirstUserWireError("unauthorized")}
    return result
  }
  async function login(username:string,password:string,signal:AbortSignal):Promise<VerifiedFirstUser>{
    invalidate()
    const generation=epoch
    let response:Response
    // Gateway requires one immutable UUIDv4 for both original POST headers.
    // Password login has no replay or automatic retry, including on timeout.
    const operationUuid=crypto.randomUUID().toLowerCase()
    try{response=await sameOrigin(ROUTES.login,"POST",signal,JSON.stringify({username,password}),undefined,operationUuid)}
    catch{throw new FirstUserWireError("unavailable")}
    if(!response.ok)throw new FirstUserWireError(classify(response.status))
    const receipt=parseLogin(await boundedJson(response))
    if(signal.aborted||epoch!==generation)throw new FirstUserWireError("unavailable")
    token=receipt.token;expiresAt=receipt.expiresAt
    try{return await current(signal)}catch{invalidate();throw new FirstUserWireError("unavailable")}
  }
  async function register(invitation:string,username:string,password:string,signal:AbortSignal):Promise<void>{
    // New original UUID is generated ONCE for exactly one first submission.
    // Any transport exception or 503 after sending is UNKNOWN; never replay.
    const operationUuid=crypto.randomUUID().toLowerCase()
    let response:Response
    try{response=await sameOrigin(ROUTES.register,"POST",signal,JSON.stringify({invitation,username,password}),undefined,operationUuid)}
    catch{throw new FirstUserWireError("uncertain")}
    if(response.status!==201){
      if(response.status===403||response.status===400||response.status===422)throw new FirstUserWireError("invalid")
      throw new FirstUserWireError("uncertain")
    }
    const dto=record(await boundedJson(response))
    fields(dto,["user_id","role"])
    if(typeof dto.user_id!=="string"||!canonicalUuid4(dto.user_id)||
      typeof dto.role!=="string"||dto.role.length<1)throw new FirstUserWireError("uncertain")
    // Registration never infers current Identity/JTI or signs a User in.
  }
  async function logout(signal:AbortSignal):Promise<boolean>{
    const original=token
    invalidate()
    if(!original)return true
    // The bearer is a credential, NEVER the original operation identity.
    // A fresh UUID pair describes this one revocation attempt only.
    const operationUuid=crypto.randomUUID().toLowerCase()
    try{return (await sameOrigin(ROUTES.logout,"POST",signal,undefined,original,operationUuid)).status===204}
    catch{return false}
  }
  return {login,current,register,logout,invalidate,expiresAt:()=>expiresAt}
}
