import {CONTROL_PANEL_AUTH_API} from "@/shared/config/control-panel-api"
/** Backend native Rauthy transaction Init, not login or authorization.
 * The one-use PoW endpoint is intentionally NOT called here: there is no
 * credential/MFA submit API yet, and consuming its challenge would burn the
 * transaction's only PoW reservation before the first factor can use it.
 * Private provider cookies, CSRF and PKCE state stay server-side.
 */
export type NativePreparation =
  | {kind:"prepared";expiresIn:number;expiresAt:number}
  | {kind:"unavailable"|"forbidden"|"invalid"|"expired";code:string}

const REQUEST:RequestInit={
  method:"POST",credentials:"same-origin",mode:"same-origin",
  cache:"no-store",redirect:"error",referrerPolicy:"no-referrer",
  headers:{Accept:"application/json","Content-Type":"application/json"},
  body:"{}",
}

function isObject(value:unknown):value is Record<string,unknown>{
  return typeof value==="object"&&value!==null&&!Array.isArray(value)
}
async function errorCode(response:Response):Promise<string>{
  try{
    const value=await response.json() as unknown
    const details=isObject(value)?value.error:null
    return isObject(details)&&typeof details.code==="string"&&
      /^[A-Z][A-Z_]{0,63}$/.test(details.code)?details.code:"NATIVE_UNAVAILABLE"
  }catch{return "NATIVE_UNAVAILABLE"}
}
/** Explicitly user-triggered same-origin, credential-free Init only.
 * Caller restricts invocation to a secure HTTPS browser context.
 */
export async function prepareNativeRauthyLogin(signal:AbortSignal):Promise<NativePreparation>{
  if(signal.aborted)return {kind:"unavailable",code:"NATIVE_PREPARATION_CANCELLED"}
  const startedAt=Date.now(),startedMonotonic=performance.now()
  try{
    const begin=await fetch(CONTROL_PANEL_AUTH_API+"/start",{...REQUEST,signal})
    if(signal.aborted)return {kind:"unavailable",code:"NATIVE_PREPARATION_CANCELLED"}
    if(begin.status!==201)return {
      kind:begin.status===403?"forbidden":"unavailable",code:await errorCode(begin),
    }
    const init=await begin.json() as unknown
    if(!isObject(init)||Object.keys(init).length!==3||
      Object.keys(init).some(key=>!["stage","authenticated","expires_in"].includes(key))||
      init.authenticated!==false||init.stage!=="first_factor_required"||
      typeof init.expires_in!=="number"||!Number.isInteger(init.expires_in)||
      init.expires_in<1||init.expires_in>300){
      return {kind:"invalid",code:"NATIVE_INIT_RESPONSE_INVALID"}
    }
    if(signal.aborted)return {kind:"unavailable",code:"NATIVE_PREPARATION_CANCELLED"}
    // Charge the whole round trip to the server TTL. Receiving a delayed
    // response must never renew a transaction created earlier on the server.
    const elapsed=performance.now()-startedMonotonic
    const expiresAt=Math.min(startedAt+init.expires_in*1000,Date.now()+init.expires_in*1000-elapsed)
    if(!Number.isFinite(elapsed)||elapsed<0||Date.now()>=expiresAt||Date.now()<startedAt)return {kind:"expired",code:"NATIVE_PREPARATION_EXPIRED"}
    return {kind:"prepared",expiresIn:init.expires_in,expiresAt}
  }catch{
    return {kind:"unavailable",code:"NATIVE_NETWORK_UNAVAILABLE"}
  }
}
