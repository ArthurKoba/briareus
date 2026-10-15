import {afterEach,describe,expect,it} from "bun:test"
import {parseCatalogMetadata,readCurrentCatalog} from "../src/features/catalog/api/current-metadata"
import type {VerifiedPlatformContext} from "../src/features/platform/api/platform-current"

const user="11111111-1111-4111-8111-111111111111"
const project="22222222-2222-4222-8222-222222222222"
const team="33333333-3333-4333-8333-333333333333"
const resource="44444444-4444-4444-8444-444444444444"
const context=(owner:"user"|"team"="user",right=true):VerifiedPlatformContext=>({
  authenticated:true,authority:"platform",rauthy:{issuer:"https://issuer.invalid",subject:"signed-id"},
  user:{id:user,role:"user",enabled:true},
  teams:owner==="team"?[{id:team,version:2,owner:true}]:[],
  projects:[{
    id:project,version:2,
    owner:owner==="team"?{kind:"team",id:team}:{kind:"user",id:user},
    permissions:right?["use_resources"]:[],
  }],
  expires_at:new Date(Date.now()+20000).toISOString(),
})
const row=(kind:"variable"|"integration"="integration",owner:"project"|"team"="project")=>({
  resource_uuid:resource,kind,
  owner:{kind:owner,id:owner==="project"?project:team},
  key:"service.production",version:5,
})
const actualFetch=globalThis.fetch
afterEach(()=>{globalThis.fetch=actualFetch})

describe("read-only Catalog metadata BFF contract",()=>{
  it("accepts only exact current nonsecret project metadata",()=>{
    expect(parseCatalogMetadata({items:[row()]},project,"integration",context())).toEqual([row()])
  })
  it("accepts team metadata only if Project ownership and membership match",()=>{
    expect(parseCatalogMetadata({items:[row("variable","team")]},project,"variable",context("team"))?.length).toBe(1)
    expect(parseCatalogMetadata({items:[row("variable","team")]},project,"variable",context("user"))).toBeNull()
  })
  it("rejects forged owner, kind, extra secret fields, duplicated IDs and invalid version",()=>{
    for(const item of [
      {...row(),owner:{kind:"project",id:team}},
      {...row(),kind:"variable"},
      {...row(),key:"/path/secret"},
      {...row(),version:0},
      {...row(),secret:"sensitive"},
      {...row(),owner:{...row().owner,credential:"x"}},
    ])expect(parseCatalogMetadata({items:[item]},project,"integration",context())).toBeNull()
    expect(parseCatalogMetadata({items:[row(),row()]},project,"integration",context())).toBeNull()
    expect(parseCatalogMetadata({items:[row()],secrets:[]},project,"integration",context())).toBeNull()
  })
  it("does not treat identity without current Project use_resources as catalog access",()=>{
    expect(parseCatalogMetadata({items:[row()]},project,"integration",context("user",false))).toBeNull()
    expect(parseCatalogMetadata({items:[row()]},project,"integration",
      {...context(),expires_at:new Date(Date.now()-1000).toISOString()})).toBeNull()
  })
  it("calls only same-origin cookie GET with exact Project and kind, no data writes",async()=>{
    let req:{url:string;init:RequestInit}|null=null
    globalThis.fetch=async (url,init)=>{
      req={url:String(url),init:init!}
      return new Response(JSON.stringify({items:[row()]}),{status:200})
    }
    const result=await readCurrentCatalog(project,"integration",context(),new AbortController().signal)
    expect(result.kind).toBe("ready")
    expect(req!.url).toBe("/api/v1/catalog?project_uuid="+project+"&kind=integration")
    expect(req!.init.method).toBe("GET")
    expect(req!.init.credentials).toBe("same-origin")
    expect(req!.init.redirect).toBe("error")
    expect(req!.init.cache).toBe("no-store")
  })
  it("never fetches an unverified Project",async()=>{
    let calls=0
    globalThis.fetch=async()=>{calls++;throw new Error("unexpected")}
    expect((await readCurrentCatalog(project,"variable",context("user",false),new AbortController().signal)).kind).toBe("forbidden")
    expect(calls).toBe(0)
  })
  it.each([[401,"unauthorized"],[403,"forbidden"],[422,"invalid"],[503,"unavailable"]] as const)(
    "fails closed on Catalog HTTP %d",async(status,expected)=>{
      globalThis.fetch=async()=>new Response(JSON.stringify({error:{code:"CATALOG_SOURCE_UNAVAILABLE"}}),{status})
      expect((await readCurrentCatalog(project,"integration",context(),new AbortController().signal)).kind).toBe(expected)
    },
  )
  it("rejects a forged successful server response with extra metadata",async()=>{
    globalThis.fetch=async()=>new Response(JSON.stringify({items:[{...row(),secret_value:"hidden"}]}),{status:200})
    expect((await readCurrentCatalog(project,"integration",context(),new AbortController().signal)).kind).toBe("invalid")
  })
  it("reports network problems as unavailable, with no retry",async()=>{
    let calls=0
    globalThis.fetch=async()=>{calls++;throw new TypeError("offline")}
    expect((await readCurrentCatalog(project,"integration",context(),new AbortController().signal)).kind).toBe("unavailable")
    expect(calls).toBe(1)
  })
})

describe("Catalog cancellation and list boundary",()=>{
  it("will not return cancelled metadata or fetch after preflight cancellation",async()=>{
    let calls=0
    const aborted=AbortSignal.abort()
    globalThis.fetch=async()=>{calls++;throw new Error('unexpected')}
    expect((await readCurrentCatalog(project,'integration',context(),aborted)).kind).toBe('unavailable')
    expect(calls).toBe(0)
    const request=new AbortController()
    globalThis.fetch=async()=>{request.abort();return new Response(JSON.stringify({items:[row()]}),{status:200})}
    expect((await readCurrentCatalog(project,'integration',context(),request.signal)).kind).toBe('unavailable')
  })
  it("accepts exactly the owner list cap without inventing a continuation cursor",()=>{
    const items=Array.from({length:50},(_,index)=>({...row(),resource_uuid:`${String(index).padStart(8,'0')}-1111-4111-8111-111111111111`}))
    expect(parseCatalogMetadata({items},project,'integration',context())).toHaveLength(50)
    expect(parseCatalogMetadata({items:[...items,{...row(),resource_uuid:user}]},project,'integration',context())).toBeNull()
  })
})

describe("bounded Catalog HTTP read",()=>{
  it("will not parse oversized metadata or oversized 503 error into visible entries",async()=>{
    globalThis.fetch=async()=>new Response(JSON.stringify({
      items:[],noise:"x".repeat(90_000),
    }),{status:200})
    expect((await readCurrentCatalog(project,"integration",context(),new AbortController().signal)).kind)
      .toBe("unavailable")
    globalThis.fetch=async()=>new Response(JSON.stringify({
      error:{code:"CATALOG_OWNER_UNAVAILABLE"},noise:"x".repeat(14_000),
    }),{status:503})
    const unavailable=await readCurrentCatalog(project,"integration",context(),new AbortController().signal)
    expect(unavailable).toEqual({kind:"unavailable",code:"UNKNOWN"})
  })
  it("interrupts a delayed successful response before parsing a current Project",async()=>{
    let cancelled=0
    const waiting=new ReadableStream<Uint8Array>({cancel(){cancelled++}})
    const request=new AbortController()
    globalThis.fetch=async()=>new Response(waiting,{status:200})
    const pending=readCurrentCatalog(project,"integration",context(),request.signal)
    setTimeout(()=>request.abort(),20)
    const result=await Promise.race([pending,new Promise<"hung">(resolve=>setTimeout(()=>resolve("hung"),300))])
    expect(result).toEqual({kind:"unavailable",code:"CATALOG_READ_CANCELLED"})
    expect(cancelled).toBe(1)
  })
})
