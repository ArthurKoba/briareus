import {afterEach,describe,expect,it} from "bun:test"
import {readRauthyPanelState,signOutRauthyPanel,type RauthyPanelIdentity} from "../src/features/platform/api/rauthy-oidc"
import {providerStateChanged} from "../src/features/platform/model/provider-state-event"
import {readPlatformContext,readProjectContext} from "../src/features/platform/api/platform-current"

const issuer="https://identity.example.invalid/auth/v1"
const user="11111111-1111-4111-8111-111111111111"
const project="33333333-3333-4333-8333-333333333333"
const identity=():RauthyPanelIdentity=>({
  authenticated:true,authority:"rauthy",subject:"provider-sub",issuer,
  client_id:"briareus-control-panel",expires_at:new Date(Date.now()+600_000).toISOString(),
  platform_membership_verified:false,permissions:[],
})
const proof=()=>({
  authenticated:true,authority:"platform",
  rauthy:{issuer,subject:"provider-sub"},
  user:{id:user,role:"user",enabled:true},
  teams:[],projects:[{id:project,version:2,owner:{kind:"user",id:user},permissions:["use_resources"]}],
  expires_at:new Date(Date.now()+20_000).toISOString(),
})
const originalFetch=globalThis.fetch
afterEach(()=>{globalThis.fetch=originalFetch})

describe("Rauthy provider session and independent Platform proof",()=>{
  it("ignores provider snapshot echoes but detects logout and realm changes",()=>{
    const current={kind:"signed_in" as const,identity:identity()}
    expect(providerStateChanged(current,{...current,identity:{...current.identity}})).toBe(false)
    expect(providerStateChanged(current,{kind:"signed_out"})).toBe(true)
    expect(providerStateChanged(current,{kind:"unavailable",reason:"network"})).toBe(true)
    expect(providerStateChanged(current,{...current,identity:{...current.identity,client_id:"other"}})).toBe(true)
    expect(providerStateChanged({kind:"signed_out"},{kind:"signed_out"})).toBe(false)
    expect(providerStateChanged(null,{kind:"signed_out"})).toBe(true)
  })
  it("requires a bound identity-only provider response",async()=>{
    const observed:string[]=[]
    globalThis.fetch=async(url,options)=>{
      observed.push(String(url))
      expect(options?.credentials).toBe("same-origin")
      expect(options?.redirect).toBe("error")
      return new Response(JSON.stringify(String(url).endsWith("/session")?
        identity():{issuer,client_id:"briareus-control-panel"}),{status:200})
    }
    const result=await readRauthyPanelState(new AbortController().signal)
    expect(result.kind).toBe("signed_in")
    expect(observed).toEqual(["/api/v1/auth/session","/api/v1/auth/config"])
  })
  it("maps Backend's anonymous 401 detail response to signed_out, never an authorized identity",async()=>{
    const observed:string[]=[],methods:string[]=[]
    globalThis.fetch=async(url,options)=>{
      observed.push(String(url));methods.push(options?.method??"GET")
      if(String(url).endsWith("/session"))return new Response(
        JSON.stringify({detail:"OIDC browser session required"}),
        {status:401,headers:{"Content-Type":"application/json"}},
      )
      return new Response(JSON.stringify({issuer,client_id:"briareus-control-panel"}),{status:200})
    }
    expect(await readRauthyPanelState(new AbortController().signal)).toEqual({kind:"signed_out"})
    expect(observed).toEqual(["/api/v1/auth/session","/api/v1/auth/config"])
    expect(methods).toEqual(["GET","GET"])
  })
  it("fails closed on wrong issuer or nonempty unverified permissions",async()=>{
    for(const invalid of [{...identity(),issuer:"https://other.invalid"},{
      ...identity(),permissions:["admin"]}]){
      globalThis.fetch=async url=>new Response(JSON.stringify(
        String(url).endsWith("/session")?invalid:{issuer,client_id:"briareus-control-panel"}
      ),{status:200})
      expect((await readRauthyPanelState(new AbortController().signal)).kind).toBe("unavailable")
    }
  })
  it("recognizes only short-lived subject-bound enabled Project ownership",async()=>{
    globalThis.fetch=async()=>new Response(JSON.stringify(proof()),{status:200})
    expect((await readPlatformContext(identity(),new AbortController().signal)).kind).toBe("verified")
    for(const invalid of [
      {...proof(),rauthy:{issuer,subject:"wrong"}},
      {...proof(),user:{id:user,role:"user",enabled:false}},
      {...proof(),expires_at:new Date(Date.now()+60000).toISOString()},
      {...proof(),projects:[{id:project,version:2,owner:{kind:"user",id:user},permissions:["super-admin"]}]},
    ]){
      globalThis.fetch=async()=>new Response(JSON.stringify(invalid),{status:200})
      expect((await readPlatformContext(identity(),new AbortController().signal)).kind).toBe("invalid_response")
    }
  })
  it("accepts first approved Rauthy operator with a real personal Project",async()=>{
    const firstOperator={
      ...proof(),
      user:{id:user,role:"operator",enabled:true},
      teams:[],
      projects:[{
        id:project,version:1,
        owner:{kind:"user",id:user},
        permissions:["use_resources","approve_agent_session"],
      }],
    }
    globalThis.fetch=async()=>new Response(JSON.stringify(firstOperator),{status:200})
    const state=await readPlatformContext(identity(),new AbortController().signal)
    expect(state.kind).toBe("verified")
    if(state.kind==="verified"){
      expect(state.context.user.role).toBe("operator")
      expect(state.context.projects).toHaveLength(1)
      expect(state.context.projects[0]?.owner).toEqual({kind:"user",id:user})
      expect(state.context.projects[0]?.permissions).toEqual([
        "use_resources","approve_agent_session",
      ])
    }
    // An operator's ID-token role or forged foreign owner UUID cannot
    // manufacture Project scope. Only exact BFF ownership is accepted.
    globalThis.fetch=async()=>new Response(JSON.stringify({
      ...firstOperator,
      projects:[{
        ...firstOperator.projects[0],
        owner:{kind:"user",id:project},
      }],
    }),{status:200})
    expect((await readPlatformContext(identity(),new AbortController().signal)).kind)
      .toBe("invalid_response")
  })
  it.each([[401,"signed_out"],[403,"denied"],[503,"unavailable"]] as const)(
    "maps membership HTTP %d to %s",async(status,kind)=>{
      globalThis.fetch=async()=>new Response(JSON.stringify({error:{code:"NO_OWNER"}}),{status})
      expect((await readPlatformContext(identity(),new AbortController().signal)).kind).toBe(kind)
    },
  )
  it("confirms logout only on HTTP204",async()=>{
    globalThis.fetch=async()=>new Response(null,{status:204})
    expect((await signOutRauthyPanel(new AbortController().signal)).kind).toBe("revoked")
    globalThis.fetch=async()=>new Response(JSON.stringify({error:{code:"NO_OWNER"}}),{status:503})
    expect((await signOutRauthyPanel(new AbortController().signal)).kind).toBe("unavailable")
    globalThis.fetch=async()=>{throw new TypeError("network")}
    expect((await signOutRauthyPanel(new AbortController().signal)).kind).toBe("uncertain")
  })
})

describe("exact Project owner context",()=>{
  it("selects one canonical Project without broad inventory fallback",async()=>{
    const paths:string[]=[]
    globalThis.fetch=async(url,options)=>{
      paths.push(String(url))
      expect(options?.method).toBe('GET');expect(options?.credentials).toBe('same-origin')
      return new Response(JSON.stringify(proof()),{status:200})
    }
    expect((await readProjectContext(identity(),project,new AbortController().signal)).kind).toBe('verified')
    expect(paths).toEqual(['/api/v1/auth/me?project_uuid='+project])
    globalThis.fetch=async(url)=>{paths.push(String(url));return new Response('{}',{status:503})}
    expect((await readProjectContext(identity(),project,new AbortController().signal)).kind).toBe('unavailable')
    expect(paths).toHaveLength(2)
    expect(paths.every(path=>path.endsWith('?project_uuid='+project))).toBe(true)
  })
  it("rejects empty, foreign or overbroad successful Project responses",async()=>{
    const one=proof().projects[0]!
    for(const projects of [[],[{...one,id:user}],[one,{...one,id:user}]]){
      globalThis.fetch=async()=>new Response(JSON.stringify({...proof(),projects}),{status:200})
      expect((await readProjectContext(identity(),project,new AbortController().signal)).kind).toBe('invalid_response')
    }
  })
  it("rejects malformed selectors before the request and discards cancelled replies",async()=>{
    let calls=0;globalThis.fetch=async()=>{calls++;throw new Error('unexpected')}
    for(const id of ['../project',project+'&other=1','']){
      expect((await readProjectContext(identity(),id,new AbortController().signal)).kind).toBe('invalid_response')
    }
    expect((await readProjectContext(identity(),project,AbortSignal.abort())).kind).toBe('unavailable')
    expect(calls).toBe(0)
    const request=new AbortController()
    globalThis.fetch=async()=>{request.abort();return new Response(JSON.stringify(proof()),{status:200})}
    expect((await readProjectContext(identity(),project,request.signal)).kind).toBe('unavailable')
  })
})
