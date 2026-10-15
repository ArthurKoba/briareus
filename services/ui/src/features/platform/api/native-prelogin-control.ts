import {CONTROL_PANEL_AUTH_API} from "@/shared/config/control-panel-api"
/** Native prelogin controls from the Backend-owned rauthy-native-v1 protocol.
 * These endpoints never collect credentials or establish Rauthy/Platform identity.
 * They are safe to call only in the existing same-origin HTTPS browser.
 */
export type NativePreloginCapabilities =
  | {kind:"supported"}
  | {kind:"unavailable"|"invalid"|"forbidden";code:string}
export type NativeCancellation =
  | {kind:"cancelled"}
  | {kind:"unavailable"|"forbidden";code:string}

function object(value:unknown):Record<string,unknown>|null{
  return value!==null&&typeof value==="object"&&!Array.isArray(value)
    ?value as Record<string,unknown>:null
}
function shape(value:Record<string,unknown>,expected:readonly string[]):boolean{
  return Object.keys(value).length===expected.length&&
    Object.keys(value).every(key=>expected.includes(key))
}
async function serverError(response:Response):Promise<string>{
  try{
    const payload=object(await response.json()),detail=object(payload?.error)
    const code=detail?.code
    return typeof code==="string"&&/^[A-Z][A-Z_]{0,63}$/.test(code)?code:"NATIVE_UNAVAILABLE"
  }catch{return "NATIVE_UNAVAILABLE"}
}

/** Read an exact protocol declaration each time before allocating a pending
 * session, rather than assuming success from a previous provider Init. */
export async function checkNativePrelogin(signal:AbortSignal):Promise<NativePreloginCapabilities>{
  if(signal.aborted)return {kind:"unavailable",code:"NATIVE_CAPABILITIES_CANCELLED"}
  try{
    const response=await fetch(CONTROL_PANEL_AUTH_API+"/capabilities",{
      method:"GET",credentials:"same-origin",mode:"same-origin",cache:"no-store",
      redirect:"error",referrerPolicy:"no-referrer",signal,
      headers:{Accept:"application/json"},
    })
    if(signal.aborted)return {kind:"unavailable",code:"NATIVE_CAPABILITIES_CANCELLED"}
    if(response.status!==200)return {kind:response.status===403?"forbidden":"unavailable",code:await serverError(response)}
    const body=object(await response.json())
    if(!body||!shape(body,["protocol","first_factor","pow","cancel","continuations"])||
      body.protocol!=="rauthy-native-v1"||body.first_factor!=="password"||
      body.pow!=="client-solved"||body.cancel!==true||
      !Array.isArray(body.continuations)||body.continuations.length!==0){
      return {kind:"invalid",code:"NATIVE_CAPABILITIES_INVALID"}
    }
    if(signal.aborted)return {kind:"unavailable",code:"NATIVE_CAPABILITIES_CANCELLED"}
    return {kind:"supported"}
  }catch{return {kind:"unavailable",code:"NATIVE_CAPABILITIES_UNAVAILABLE"}}
}

/** Only explicit user cancellation; never revoke a completed signed-in session.
 * A timeout is uncertain: the UI must not report that cleanup succeeded. */
export async function cancelNativePrelogin(signal:AbortSignal):Promise<NativeCancellation>{
  if(signal.aborted)return {kind:"unavailable",code:"NATIVE_CANCEL_CANCELLED"}
  try{
    const response=await fetch(CONTROL_PANEL_AUTH_API+"/cancel",{
      method:"POST",credentials:"same-origin",mode:"same-origin",cache:"no-store",
      redirect:"error",referrerPolicy:"no-referrer",signal,
      headers:{Accept:"application/json","Content-Type":"application/json"},body:"{}",
    })
    if(signal.aborted)return {kind:"unavailable",code:"NATIVE_CANCEL_UNCERTAIN"}
    if(response.status===204)return {kind:"cancelled"}
    return {kind:response.status===403?"forbidden":"unavailable",code:await serverError(response)}
  }catch{return {kind:"unavailable",code:"NATIVE_CANCEL_UNCERTAIN"}}
}
