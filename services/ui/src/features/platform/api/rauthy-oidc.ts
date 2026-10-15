import {CONTROL_PANEL_AUTH_API} from "@/shared/config/control-panel-api"
/** Same-origin, server-owned Rauthy code+PKCE session; no browser OAuth tokens. */
export type RauthyPanelIdentity = {
  authenticated: true
  authority: "rauthy"
  subject: string
  issuer: string
  client_id: string
  expires_at: string
  platform_membership_verified: false
  permissions: []
}

export type RauthyFailure =
  | "provider_unavailable"
  | "session_unavailable"
  | "forbidden"
  | "invalid_response"
  | "network"

export type RauthyPanelState =
  | { kind: "unavailable"; reason: RauthyFailure }
  | { kind: "signed_out" }
  | { kind: "signed_in"; identity: RauthyPanelIdentity }

export type RauthyLogoutResult =
  | { kind: "revoked" }
  | { kind: "forbidden" | "unavailable" | "uncertain" }

const CONFIG = CONTROL_PANEL_AUTH_API+"/config"
const SESSION = CONTROL_PANEL_AUTH_API+"/session"
const LOGOUT = CONTROL_PANEL_AUTH_API+"/logout"

interface BrowserConfiguration { issuer: string; client_id: string }
function object(value: unknown): Record<string, unknown> | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null
}
function validConfiguration(value: unknown): BrowserConfiguration | null {
  const data=object(value)
  if(!data||typeof data.issuer!=="string"||typeof data.client_id!=="string"||
    data.client_id.trim().length===0)return null
  try {
    const url=new URL(data.issuer)
    if(url.protocol!=="https:"||url.username||url.password||url.search||url.hash)return null
  } catch {return null}
  return {issuer:data.issuer,client_id:data.client_id}
}
function verifiedIdentity(value: unknown, trusted: BrowserConfiguration): RauthyPanelIdentity | null {
  const item=object(value)
  if(!item||item.authenticated!==true||item.authority!=="rauthy"||
    typeof item.subject!=="string"||item.subject.length===0||
    item.issuer!==trusted.issuer||item.client_id!==trusted.client_id||
    typeof item.expires_at!=="string"||
    !/(?:Z|[+-][0-2][0-9]:[0-5][0-9])$/.test(item.expires_at)||
    !Number.isFinite(Date.parse(item.expires_at))||
    Date.parse(item.expires_at)<=Date.now()||
    item.platform_membership_verified!==false||
    !Array.isArray(item.permissions)||item.permissions.length!==0)return null
  return {
    authenticated:true,authority:"rauthy",subject:item.subject,
    issuer:item.issuer,client_id:item.client_id,expires_at:item.expires_at,
    platform_membership_verified:false,permissions:[],
  }
}

/** 200 config is only OIDC discovery, 401 session is signed-out, never a User grant. */
export async function readRauthyPanelState(signal: AbortSignal): Promise<RauthyPanelState> {
  const request: RequestInit={
    method:"GET",signal,credentials:"same-origin",mode:"same-origin",
    redirect:"error",referrerPolicy:"no-referrer",cache:"no-store",
    headers:{Accept:"application/json"},
  }
  try {
    // The browser session is the only identity proof. Configuration does not
    // imply logged-in state, and a malformed 200 must never become a principal.
    const session=await fetch(SESSION,request)
    if(session.status===403)return {kind:"unavailable",reason:"forbidden"}
    if(session.status!==200&&session.status!==401){
      return {kind:"unavailable",reason:"session_unavailable"}
    }
    const config=await fetch(CONFIG,request)
    if(!config.ok)return {kind:"unavailable",reason:"provider_unavailable"}
    const metadata=validConfiguration(await config.json())
    if(!metadata)return {kind:"unavailable",reason:"invalid_response"}
    if(session.status===401)return {kind:"signed_out"}
    const identity=verifiedIdentity(await session.json(),metadata)
    return identity?{kind:"signed_in",identity}:{kind:"unavailable",reason:"invalid_response"}
  }catch{return {kind:"unavailable",reason:"network"}}
}

/** Only a server 204 is proof that private Valkey session deletion committed. */
export async function signOutRauthyPanel(signal: AbortSignal): Promise<RauthyLogoutResult> {
  try {
    const response=await fetch(LOGOUT,{
      method:"POST",signal,credentials:"same-origin",mode:"same-origin",
      redirect:"error",referrerPolicy:"no-referrer",cache:"no-store",
      headers:{Accept:"application/json"},
    })
    if(response.status===204)return {kind:"revoked"}
    if(response.status===403)return {kind:"forbidden"}
    if(response.status===503)return {kind:"unavailable"}
    return {kind:"uncertain"}
  }catch{return {kind:"uncertain"}}
}
