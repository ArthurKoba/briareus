import {describe,expect,it} from "bun:test"
import {prepareNativeRauthyLogin} from "../src/features/platform/api/native-rauthy"

function apiReply(status:number,body:unknown):Response {
  return new Response(JSON.stringify(body),{status,headers:{"Content-Type":"application/json"}})
}
function scopeTest(responses:Response[],run:(requests:{path:string;options:RequestInit}[])=>Promise<void>):Promise<void>{
  const original=globalThis.fetch
  const requests:{path:string;options:RequestInit}[]=[]
  let count=0
  globalThis.fetch=async (input:RequestInfo|URL,init?:RequestInit):Promise<Response>=>{
    requests.push({path:String(input),options:init??{}})
    return responses[count++]??apiReply(503,{error:{code:"NATIVE_UNAVAILABLE"}})
  }
  return run(requests).finally(()=>{globalThis.fetch=original})
}
describe("native Rauthy credential-free handshake",()=>{
  it("checks exact same-origin Init without wasting a one-use PoW",async()=>{
    await scopeTest([
      apiReply(201,{stage:"first_factor_required",authenticated:false,expires_in:120}),
    ],async requests=>{
      const result=await prepareNativeRauthyLogin(new AbortController().signal)
      expect(result).toMatchObject({kind:"prepared",expiresIn:120})
      if(result.kind==="prepared")expect(result.expiresAt).toBeGreaterThan(Date.now())
      expect(requests.map(row=>row.path)).toEqual([
        "/api/v1/auth/start",
      ])
      for(const {options} of requests){
        expect(options.method).toBe("POST")
        expect(options.body).toBe("{}")
        expect(options.credentials).toBe("same-origin")
        expect(options.mode).toBe("same-origin")
        expect(options.redirect).toBe("error")
      }
    })
  })
  it("rejects an untrusted Init without advancing to PoW",async()=>{
    await scopeTest([apiReply(201,{stage:"first_factor_required",authenticated:true,expires_in:120})],async requests=>{
      expect(await prepareNativeRauthyLogin(new AbortController().signal))
        .toEqual({kind:"invalid",code:"NATIVE_INIT_RESPONSE_INVALID"})
      expect(requests.length).toBe(1)
    })
  })
  it("never treats provider failure or invalid success as authentication",async()=>{
    await scopeTest([apiReply(503,{error:{code:"NATIVE_INIT_UNAVAILABLE"}})],async requests=>{
      expect(await prepareNativeRauthyLogin(new AbortController().signal))
        .toEqual({kind:"unavailable",code:"NATIVE_INIT_UNAVAILABLE"})
      expect(requests.length).toBe(1)
    })
    await scopeTest([apiReply(201,{stage:"first_factor_required",authenticated:false,expires_in:120,access_token:"forged"})],async requests=>{
      expect(await prepareNativeRauthyLogin(new AbortController().signal))
        .toEqual({kind:"invalid",code:"NATIVE_INIT_RESPONSE_INVALID"})
      expect(requests.length).toBe(1)
    })
    await scopeTest([apiReply(201,{stage:"first_factor_required",authenticated:false,expires_in:301})],async requests=>{
      expect(await prepareNativeRauthyLogin(new AbortController().signal))
        .toEqual({kind:"invalid",code:"NATIVE_INIT_RESPONSE_INVALID"})
      expect(requests.length).toBe(1)
    })
    await scopeTest([apiReply(403,{error:{code:"NATIVE_ORIGIN_OR_REQUEST_DENIED"}})],async requests=>{
      expect(await prepareNativeRauthyLogin(new AbortController().signal))
        .toEqual({kind:"forbidden",code:"NATIVE_ORIGIN_OR_REQUEST_DENIED"})
      expect(requests.length).toBe(1)
    })
  })
})

describe("native transaction deadlines",()=>{
  it("subtracts response delay from preparation lifetime instead of renewing it",async()=>{
    const previous=Date.now,fetch=globalThis.fetch;let now=1_000_000
    try{
      Date.now=()=>now
      globalThis.fetch=async()=>{now+=5000;return apiReply(201,{stage:'first_factor_required',authenticated:false,expires_in:10})}
      expect(await prepareNativeRauthyLogin(new AbortController().signal)).toEqual({kind:'prepared',expiresIn:10,expiresAt:1_010_000})
    }finally{Date.now=previous;globalThis.fetch=fetch}
  })
  it("rejects an expired delayed Init and stops before a cancelled request",async()=>{
    const previous=Date.now,fetch=globalThis.fetch;let now=2_000_000,calls=0
    try{
      Date.now=()=>now
      globalThis.fetch=async()=>{calls++;now+=3000;return apiReply(201,{stage:'first_factor_required',authenticated:false,expires_in:2})}
      expect((await prepareNativeRauthyLogin(new AbortController().signal)).kind).toBe('expired')
      expect(await prepareNativeRauthyLogin(AbortSignal.abort())).toEqual({kind:'unavailable',code:'NATIVE_PREPARATION_CANCELLED'})
      expect(calls).toBe(1)
    }finally{Date.now=previous;globalThis.fetch=fetch}
  })
  it("never publishes a success returned after cancellation",async()=>{
    const fetch=globalThis.fetch,request=new AbortController()
    try{
      globalThis.fetch=async()=>{request.abort();return apiReply(201,{stage:'first_factor_required',authenticated:false,expires_in:120})}
      expect(await prepareNativeRauthyLogin(request.signal)).toEqual({kind:'unavailable',code:'NATIVE_PREPARATION_CANCELLED'})
    }finally{globalThis.fetch=fetch}
  })
})

describe("native Init monotonic lifetime",()=>{
  it("charges monotonic response delay even when the wall clock is paused",async()=>{
    const {spyOn}=await import('bun:test')
    const now=Date.now(),wall=spyOn(Date,'now').mockReturnValue(now)
    let elapsed=100
    const monotonic=spyOn(performance,'now').mockImplementation(()=>elapsed)
    const original=globalThis.fetch
    try{
      globalThis.fetch=async()=>{elapsed+=2001;return apiReply(201,{stage:'first_factor_required',authenticated:false,expires_in:2})}
      expect((await prepareNativeRauthyLogin(new AbortController().signal)).kind).toBe('expired')
    }finally{globalThis.fetch=original;monotonic.mockRestore();wall.mockRestore()}
  })
})
