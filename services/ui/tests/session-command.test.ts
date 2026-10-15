import {afterEach,describe,expect,it} from "bun:test"
import {revokeVerifiedSession,type SessionCommandContext} from "../src/features/agent-sessions/model/revoke-current"
import type {CurrentAgentSession} from "../src/features/agent-sessions/api/current-sessions"
const project="11111111-1111-4111-8111-111111111111",actor="22222222-2222-4222-8222-222222222222",id="33333333-3333-4333-8333-333333333333"
const setup=()=>{
  const item:CurrentAgentSession={session_uuid:id,project_uuid:project,created_by_user_uuid:actor,revision:4,status:"active",is_elevated:false,elevation_policy:"requestable",hard_expires_at:new Date(Date.now()+3600_000).toISOString(),operations:["files.read","project.metadata.read"],resources:[],allowed_actions:["revoke"]}
  const context:SessionCommandContext={projectId:project,actorId:actor,canApprove:true,proofExpiresAt:new Date(Date.now()+20_000).toISOString()}
  return {item,context,revoked:{...item,status:"revoked" as const,revision:5,allowed_actions:[]}}
}
const realFetch=globalThis.fetch
afterEach(()=>{globalThis.fetch=realFetch})
const json=(value:unknown,status=200)=>new Response(JSON.stringify(value),{status})
describe("exact-session revoke command",()=>{
  it("confirms one POST using individual GETs, with proof renewal during dispatch",async()=>{
    const {item,context,revoked}=setup();const paths:string[]=[]
    globalThis.fetch=async(url,options)=>{
      paths.push((options?.method??"GET")+" "+url)
      if(options?.method==="POST"){
        context.proofExpiresAt=new Date(Date.now()+25_000).toISOString()
        return json({session_uuid:id,project_uuid:project,status:"revoked",revision:5})
      }
      return json(paths.length===1?item:revoked)
    }
    const result=await revokeVerifiedSession(item,{signal:new AbortController().signal,context:()=>context,verify:async()=>"authorized"})
    expect(result.kind).toBe("confirmed")
    expect(paths).toEqual([
      'GET /api/v1/agent-sessions/'+id+'?project_uuid='+project,
      'POST /api/v1/agent-sessions/'+id+'/revoke',
      'GET /api/v1/agent-sessions/'+id+'?project_uuid='+project,
    ])
  })
  it("will not issue a POST when the selected revision has changed",async()=>{
    const {item,context}=setup();let calls=0
    globalThis.fetch=async(_url,options)=>{calls++;expect(options?.method).toBe('GET');return json({...item,revision:5})}
    expect((await revokeVerifiedSession(item,{signal:new AbortController().signal,context:()=>context,verify:async()=>"authorized"})).kind).toBe("conflict")
    expect(calls).toBe(1)
  })
  it("stops on changed actor during verification or revoked permission during read",async()=>{
    for(const atRead of [false,true]){
      const {item,context}=setup();let calls=0
      globalThis.fetch=async()=>{calls++;context.canApprove=false;return json(item)}
      const result=await revokeVerifiedSession(item,{signal:new AbortController().signal,context:()=>context,verify:async()=>{
        if(!atRead)context.actorId=id
        return "authorized"
      }})
      expect(result.kind).toBe("cancelled");expect(calls).toBe(atRead?1:0)
    }
  })
  it("never claims success from missing or still-active final state",async()=>{
    for(const status of [200,404,503]){
      const {item,context}=setup();let calls=0
      globalThis.fetch=async(_url,options)=>{
        calls++
        if(options?.method==='POST')return json({session_uuid:id,project_uuid:project,status:'revoked',revision:5})
        return json(item,calls===1?200:status)
      }
      expect((await revokeVerifiedSession(item,{signal:new AbortController().signal,context:()=>context,verify:async()=>"authorized"})).kind).toBe("uncertain")
      expect(calls).toBe(3)
    }
  })
  it("does not replay a lost/503 POST and treats aborted result as uncertain",async()=>{
    for(const mode of ['lost','503','aborted']){
      const {item,context}=setup();const request=new AbortController();let calls=0
      globalThis.fetch=async(_url,options)=>{
        calls++
        if(options?.method!=='POST')return json(item)
        if(mode==='lost')throw new TypeError('lost')
        if(mode==='503')return json({},503)
        request.abort();return json({session_uuid:id,project_uuid:project,status:'revoked',revision:5})
      }
      expect((await revokeVerifiedSession(item,{signal:request.signal,context:()=>context,verify:async()=>"authorized"})).kind).toBe(mode==='aborted'?'uncertain':'observed')
      expect(calls).toBe(mode==='aborted'?2:3)
    }
  })
})

describe("post-loss current-state reconciliation",()=>{
  it("observes a revoked session after 503 but never invents the missing command receipt",async()=>{
    const {item,context,revoked}=setup();let reads=0,posts=0
    globalThis.fetch=async(_url,options)=>{
      if(options?.method==='POST'){posts++;return json({error:{code:'OWNER_REPLY_LOST'}},503)}
      return json(++reads===1?item:revoked)
    }
    const result=await revokeVerifiedSession(item,{signal:new AbortController().signal,context:()=>context,verify:async()=>"authorized"})
    expect(result).toEqual({kind:'observed',item:revoked})
    expect(posts).toBe(1);expect(reads).toBe(2)
  })
  it("stays uncertain when an ambiguous write is followed by a missing or foreign record",async()=>{
    for(const mode of ['missing','foreign','regressed']){
      const {item,context,revoked}=setup();let calls=0
      globalThis.fetch=async(_url,options)=>{
        calls++
        if(options?.method==='POST')throw new TypeError('reply lost')
        if(calls===1)return json(item)
        if(mode==='missing')return json({error:{code:'AGENT_SESSION_NOT_FOUND'}},404)
        return json(mode==='foreign'?{...revoked,created_by_user_uuid:id}:{...revoked,revision:3})
      }
      expect((await revokeVerifiedSession(item,{signal:new AbortController().signal,context:()=>context,verify:async()=>"authorized"})).kind).toBe('uncertain')
      expect(calls).toBe(3)
    }
  })
  it("does not perform a follow-up read after authorization denial or a changed caller",async()=>{
    for(const mode of ['403','identity']){
      const {item,context}=setup();let calls=0
      globalThis.fetch=async(_url,options)=>{
        calls++
        if(options?.method!=='POST')return json(item)
        if(mode==='identity')context.actorId=id
        return json({error:{code:'DENIED'}},mode==='403'?403:503)
      }
      expect((await revokeVerifiedSession(item,{signal:new AbortController().signal,context:()=>context,verify:async()=>"authorized"})).kind).toBe(mode==='403'?'forbidden':'uncertain')
      expect(calls).toBe(2)
    }
  })
})
