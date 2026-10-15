import {afterEach,describe,expect,it} from "bun:test"
import {requestSessionElevation,type ElevationTarget} from "../src/features/approvals/api/request-elevation"
import type {HandEffectScope} from "../src/shared/lib/hand-effect-scope"
const project="11111111-1111-4111-8111-111111111111",actor="22222222-2222-4222-8222-222222222222"
const session="33333333-3333-4333-8333-333333333333",id="44444444-4444-4444-8444-444444444444"
const target=():ElevationTarget=>({project_uuid:project,session_uuid:session,revision:3,status:"active",elevation_policy:"requestable",hard_expires_at:new Date(Date.now()+3600_000).toISOString()})
const resources:HandEffectScope[]=[{hand:"files",tool:"read_file",action:"files.read",resource:{kind:"workspace_path",id:"README.md"}}]
const pending=()=>({id,project_uuid:project,agent_session_uuid:session,requested_by_user_uuid:actor,status:"pending",version:1,requested_operations:["files.read"],requested_resources:resources,requested_expires_at:new Date(Date.now()+60_000).toISOString(),resolved_by_user_uuid:null,issued_session_uuid:null,allowed_actions:[]})
const original=globalThis.fetch
afterEach(()=>{globalThis.fetch=original})
describe("source-backed pending elevation request, not a grant",()=>{
  it("uses one exact cookie-bound idempotent request with bounded scopes and revision",async()=>{
    const calls:RequestInit[]=[]
    globalThis.fetch=async(url,options)=>{
      expect(url).toBe("/api/v1/approvals");calls.push(options!)
      return new Response(JSON.stringify({...pending(),id:(options!.headers as Record<string,string>)["Operation-UUID"]}),{status:202})
    }
    const result=await requestSessionElevation(target(),resources,60,actor,new AbortController().signal)
    expect(result.kind).toBe("pending");expect(calls.length).toBe(1)
    const request=calls[0]!,headers=request.headers as Record<string,string>
    expect(headers["Operation-UUID"]).toBe(headers["Idempotency-Key"])
    expect(request.credentials).toBe("same-origin")
    expect(request.redirect).toBe("error")
    expect(JSON.parse(request.body as string)).toEqual({project_uuid:project,agent_session_uuid:session,operations:["files.read"],resources,seconds:60,expected_grant_revision:3})
  })
  it("does not send invalid, expired, fixed, empty or duplicate scope requests",async()=>{
    let calls=0;globalThis.fetch=async()=>{calls++;throw new Error('unexpected')}
    for(const invalid of [{...target(),elevation_policy:"fixed" as const},{...target(),status:"revoked" as const},{...target(),revision:0},
      {...target(),hard_expires_at:new Date(Date.now()-1000).toISOString()},
      {...target(),hard_expires_at:"2099-01-01T12:00:00"}]){
      expect((await requestSessionElevation(invalid,resources,60,actor,new AbortController().signal)).kind).toBe("invalid")
    }
    for(const list of [[],[...resources,...resources]]){
      expect((await requestSessionElevation(target(),list,60,actor,new AbortController().signal)).kind).toBe("invalid")
    }
    expect((await requestSessionElevation(target(),resources,301,actor,new AbortController().signal)).kind).toBe("invalid")
    expect(calls).toBe(0)
  })
  it("refuses broadened resources, approved state, foreign actor or already-issued grants",async()=>{
    for(const invalid of [
      {...pending(),requested_by_user_uuid:id},
      {...pending(),requested_resources:[{...resources[0],resource:{kind:"workspace_path",id:"other.md"}}]},
      {...pending(),status:"approved"},{...pending(),issued_session_uuid:session},
    ]){
      globalThis.fetch=async(_url,options)=>new Response(JSON.stringify({...invalid,id:(options!.headers as Record<string,string>)["Operation-UUID"]}),{status:202})
      expect((await requestSessionElevation(target(),resources,60,actor,new AbortController().signal)).kind).toBe("uncertain")
    }
  })
  it("does not repeat a lost/503 POST and reports denial/conflict distinctly",async()=>{
    let lostCalls=0
    globalThis.fetch=async()=>{lostCalls++;throw new TypeError("lost response")}
    expect((await requestSessionElevation(target(),resources,60,actor,new AbortController().signal)).kind).toBe("uncertain")
    expect(lostCalls).toBe(1)
    for(const [status,kind] of [[401,"unauthorized"],[403,"forbidden"],[409,"conflict"],[422,"invalid"],[503,"uncertain"]] as const){
      let calls=0;globalThis.fetch=async()=>{calls++;return new Response("{}",{status})}
      expect((await requestSessionElevation(target(),resources,60,actor,new AbortController().signal)).kind).toBe(kind)
      expect(calls).toBe(1)
    }
  })
})

describe("pending request receipt correlation",()=>{
  it("requires approval UUID to equal the submitted operation UUID",async()=>{
    globalThis.fetch=async()=>new Response(JSON.stringify(pending()),{status:202})
    expect((await requestSessionElevation(target(),resources,60,actor,new AbortController().signal)).kind).toBe('uncertain')
  })
  it("rejects a compact selector for a different Project before POST",async()=>{
    const scope={...resources[0]!,resource:{kind:'workspace_path',id:'project-path-v1:'+session+':'+('c'.repeat(64))}}
    let calls=0;globalThis.fetch=async()=>{calls++;throw new Error('unexpected')}
    expect((await requestSessionElevation(target(),[scope],60,actor,new AbortController().signal)).kind).toBe('invalid')
    expect(calls).toBe(0)
  })
})
