import {afterEach,describe,expect,it} from "bun:test"
import {resolveCurrentApproval,type ApprovalCommandContext} from "../src/features/approvals/model/resolve-current"
import {parseApproval} from "../src/features/approvals/api/control-panel"
const project="11111111-1111-4111-8111-111111111111"
const actor="22222222-2222-4222-8222-222222222222"
const requester="33333333-3333-4333-8333-333333333333"
const session="44444444-4444-4444-8444-444444444444"
const fixture=()=>parseApproval({
  id:"55555555-5555-4555-8555-555555555555",project_uuid:project,
  agent_session_uuid:session,requested_by_user_uuid:requester,
  status:"pending",version:1,requested_operations:["files.read"],
  requested_resources:[{hand:"files",tool:"read_file",action:"files.read",resource:{kind:"workspace_path",id:"README.md"}}],
  requested_expires_at:new Date(Date.now()+120_000).toISOString(),
  resolved_by_user_uuid:null,issued_session_uuid:null,allowed_actions:["approve","deny"],
},project)!
const original=globalThis.fetch
afterEach(()=>{globalThis.fetch=original})
const response=(value:unknown,status=200)=>new Response(JSON.stringify(value),{status})
function setup(){
  const row=fixture()
  const context:ApprovalCommandContext={projectId:project,actorId:actor,proofExpiresAt:new Date(Date.now()+25_000).toISOString(),canApprove:true,rows:[row]}
  const resolved={...row,version:2,status:"approved",resolved_by_user_uuid:actor,issued_session_uuid:"77777777-7777-4777-8777-777777777777",allowed_actions:[]}
  return {row,context,resolved}
}
describe("revision-fenced approval command orchestration",()=>{
  it("survives same-scope proof renewal and confirms only via GET/POST/GET",async()=>{
    const {row,context,resolved}=setup();const methods:string[]=[]
    globalThis.fetch=async(_url,options)=>{
      methods.push(options?.method??"GET")
      if(options?.method==="POST"){
        context.proofExpiresAt=new Date(Date.now()+30_000).toISOString()
        const headers=options.headers as Record<string,string>
        expect(headers["Operation-UUID"]).toBe(headers["Idempotency-Key"])
        return response(resolved)
      }
      return response({items:[methods.length===1?row:resolved]})
    }
    const result=await resolveCurrentApproval(row,"approve",{signal:new AbortController().signal,context:()=>context,verify:async()=>"authorized"})
    expect(result.kind).toBe("confirmed")
    expect(methods).toEqual(["GET","POST","GET"])
  })
  it("stops before any effect after actor changes during membership verification",async()=>{
    const {row,context}=setup();let calls=0
    globalThis.fetch=async()=>{calls++;throw new Error("unexpected")}
    const result=await resolveCurrentApproval(row,"approve",{signal:new AbortController().signal,context:()=>context,verify:async()=>{context.actorId=requester;return "authorized"}})
    expect(result.kind).toBe("cancelled");expect(calls).toBe(0)
  })
  it("rejects changed revision on fresh GET without dispatching POST",async()=>{
    const {row,context}=setup();const calls:string[]=[]
    globalThis.fetch=async(_url,options)=>{calls.push(options?.method??"GET");return response({items:[{...row,version:2}]})}
    expect((await resolveCurrentApproval(row,"deny",{signal:new AbortController().signal,context:()=>context,verify:async()=>"authorized"})).kind).toBe("conflict")
    expect(calls).toEqual(["GET"])
  })
  it("does not send POST when the owner proof is lost during the fresh GET",async()=>{
    const {row,context}=setup();const calls:string[]=[]
    globalThis.fetch=async(_url,options)=>{calls.push(options?.method??"GET");context.canApprove=false;return response({items:[row]})}
    expect((await resolveCurrentApproval(row,"approve",{signal:new AbortController().signal,context:()=>context,verify:async()=>"authorized"})).kind).toBe("cancelled")
    expect(calls).toEqual(["GET"])
  })
  it("observes the original request after a lost POST without replaying it",async()=>{
    for(const network of [true,false]){
      const {row,context}=setup();const calls:string[]=[]
      globalThis.fetch=async(_url,options)=>{
        calls.push(options?.method??"GET")
        if(options?.method==="POST"){
          if(network)throw new TypeError("lost response")
          return response({error:{code:"OWNER_UNAVAILABLE"}},503)
        }
        return response({items:[row]})
      }
      expect((await resolveCurrentApproval(row,"approve",{signal:new AbortController().signal,context:()=>context,verify:async()=>"authorized"})).kind).toBe("observed")
      expect(calls).toEqual(["GET","POST","GET"])
    }
  })
  it("refuses false success when a subsequent listing still shows pending",async()=>{
    const {row,context,resolved}=setup()
    globalThis.fetch=async(_url,options)=>response(options?.method==="POST"?resolved:{items:[row]})
    expect((await resolveCurrentApproval(row,"approve",{signal:new AbortController().signal,context:()=>context,verify:async()=>"authorized"})).kind).toBe("uncertain")
  })
})

describe("approval recovery and final receipt identity",()=>{
  it("observes committed approval or rejection after reply loss, without attributing a command receipt",async()=>{
    for(const approved of [true,false]){
      const {row,context,resolved}=setup();let posts=0,gets=0
      const final={...resolved,status:approved?'approved':'rejected',issued_session_uuid:approved?resolved.issued_session_uuid:null}
      globalThis.fetch=async(_url,options)=>{
        if(options?.method==='POST'){posts++;throw new TypeError('reply lost')}
        return response({items:[++gets===1?row:final]})
      }
      expect((await resolveCurrentApproval(row,approved?'approve':'deny',{signal:new AbortController().signal,context:()=>context,verify:async()=>"authorized"})).kind).toBe('observed')
      expect(posts).toBe(1);expect(gets).toBe(2)
    }
  })
  it("rejects a changed resource, child session or revision in the final GET",async()=>{
    for(const mode of ['resource','child','revision']){
      const {row,context,resolved}=setup();let gets=0
      const final=mode==='resource'?{...resolved,requested_resources:[{...row.requested_resources[0]!,resource:{kind:'workspace_path',id:'other.txt'}}]}:
        mode==='child'?{...resolved,issued_session_uuid:'88888888-8888-4888-8888-888888888888'}:{...resolved,version:3}
      globalThis.fetch=async(_url,options)=>options?.method==='POST'?response(resolved):response({items:[++gets===1?row:final]})
      expect((await resolveCurrentApproval(row,'approve',{signal:new AbortController().signal,context:()=>context,verify:async()=>"authorized"})).kind).toBe('uncertain')
    }
  })
  it("cannot infer resolution from absence in the capped list or a denied caller",async()=>{
    for(const mode of ['absent','denied','changed']){
      const {row,context}=setup();let calls=0
      globalThis.fetch=async(_url,options)=>{
        calls++
        if(options?.method==='POST'){
          if(mode==='changed')context.actorId=requester
          return response({},mode==='denied'?403:503)
        }
        return response({items:calls===1?[row]:[]})
      }
      expect((await resolveCurrentApproval(row,'approve',{signal:new AbortController().signal,context:()=>context,verify:async()=>"authorized"})).kind).toBe(mode==='denied'?'forbidden':'uncertain')
      expect(calls).toBe(mode==='absent'?3:2)
    }
  })
})

describe("cancelled approval transport",()=>{
  it("does not dispatch a pre-cancelled read or decision, and discards a late success",async()=>{
    const {readProjectApprovals,resolveProjectApproval}=await import('../src/features/approvals/api/control-panel')
    const {row,resolved}=setup();let calls=0
    globalThis.fetch=async()=>{calls++;return response(resolved)}
    expect((await readProjectApprovals(project,AbortSignal.abort())).kind).toBe('unavailable')
    expect((await resolveProjectApproval(row,'approve',AbortSignal.abort())).kind).toBe('unavailable')
    expect(calls).toBe(0)
    const request=new AbortController()
    globalThis.fetch=async()=>{request.abort();return response(resolved)}
    expect((await resolveProjectApproval(row,'approve',request.signal)).kind).toBe('uncertain')
  })
})
