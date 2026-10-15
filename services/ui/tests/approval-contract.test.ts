import { afterEach, describe, expect, it } from "bun:test"
import { parseApproval, readProjectApprovals, resolveProjectApproval, approvalStillCurrentForActor } from "../src/features/approvals/api/control-panel"

const project = "11111111-1111-4111-8111-111111111111"
const session = "22222222-2222-4222-8222-222222222222"
const user = "33333333-3333-4333-8333-333333333333"
const approval = "44444444-4444-4444-8444-444444444444"
const item = () => ({
  id:approval,project_uuid:project,agent_session_uuid:session,
  requested_by_user_uuid:user,status:"pending",version:1,
  requested_operations:["files.read"],
  requested_resources:[{hand:"files",tool:"read_file",action:"files.read",
    resource:{kind:"workspace_path",id:"src/main.ts"}}],
  requested_expires_at:new Date(Date.now()+120_000).toISOString(),
  resolved_by_user_uuid:null,issued_session_uuid:null,allowed_actions:["approve","deny"],
})
const originalFetch=globalThis.fetch
afterEach(()=>{globalThis.fetch=originalFetch})
describe("source-scoped approval BFF",()=>{
  it("accepts an exact current Project approval",()=>{
    expect(parseApproval(item(),project)?.allowed_actions).toEqual(["approve","deny"])
  })
  it("rejects a stale approval dialog after Project, actor, row or revision changes",()=>{
    const selected=parseApproval(item(),project)!
    const otherProject="55555555-5555-4555-8555-555555555555"
    const otherActor="66666666-6666-4666-8666-666666666666"
    expect(approvalStillCurrentForActor(selected,[selected],"approve",project,otherActor)).toBe(true)
    expect(approvalStillCurrentForActor(selected,[selected],"approve",otherProject,otherActor)).toBe(false)
    expect(approvalStillCurrentForActor(selected,[selected],"approve",project,user)).toBe(false)
    expect(approvalStillCurrentForActor(selected,[],"approve",project,otherActor)).toBe(false)
    expect(approvalStillCurrentForActor(selected,[{...selected,version:2}],"approve",project,otherActor)).toBe(false)
    expect(approvalStillCurrentForActor(selected,[{...selected,allowed_actions:[]}],"approve",project,otherActor)).toBe(false)
    expect(approvalStillCurrentForActor(selected,[{...selected,requested_by_user_uuid:otherActor}],"approve",project,otherActor)).toBe(false)
    expect(approvalStillCurrentForActor(selected,[selected],"deny",project,otherActor,
      Date.parse(selected.requested_expires_at)+1)).toBe(false)
  })
  it("rejects cross-project rows, unregistered effects and resolved actions",()=>{
    expect(parseApproval({...item(),project_uuid:session},project)).toBeNull()
    expect(parseApproval({...item(),status:"approved"},project)).toBeNull()
    expect(parseApproval({...item(),requested_resources:[{hand:"files",tool:"read_file",action:"terminal.execute",
      resource:{kind:"workspace_path",id:"src/main.ts"}}]},project)).toBeNull()
  })
  it("rejects pending approval without exact per-action resource coverage",()=>{
    const row=item()
    expect(parseApproval({...row,requested_resources:[]},project)).toBeNull()
    expect(parseApproval({...row,requested_operations:["files.read","files.write"]},project)).toBeNull()
    expect(parseApproval({...row,requested_resources:[...row.requested_resources,...row.requested_resources]},project)).toBeNull()
    expect(parseApproval({...row,requested_resources:[{...row.requested_resources[0],hand:"web"}]},project)).toBeNull()
  })
  it("rejects timezone-less pending requests rather than guessing browser-local expiry",()=>{
    const raw=item()
    expect(parseApproval({...raw,requested_expires_at:"2026-10-14T19:00:00"},project)).toBeNull()
  })
  it("does not render successful list when IDs repeat",async()=>{
    globalThis.fetch=async()=>new Response(JSON.stringify({items:[item(),item()]}),{status:200})
    expect((await readProjectApprovals(project,new AbortController().signal)).kind).toBe("invalid")
  })
  it("uses a same-origin GET and verifies 503 as unavailable",async()=>{
    let request: {url:string;options:RequestInit}|undefined
    globalThis.fetch=async(url,options)=>{
      request={url:String(url),options:options!}
      return new Response(JSON.stringify({error:{code:"APPROVAL_OWNER_UNAVAILABLE"}}),{status:503})
    }
    const result=await readProjectApprovals(project,new AbortController().signal)
    expect(result.kind).toBe("unavailable")
    expect(request?.url).toBe("/api/v1/approvals?project_uuid="+project)
    expect(request?.options.credentials).toBe("same-origin")
  })
  it("requires server-granted allowed action before POST",async()=>{
    let attempts=0
    globalThis.fetch=async()=>{attempts++;throw new Error("unexpected")}
    const record=parseApproval({...item(),allowed_actions:[]},project)!
    expect((await resolveProjectApproval(record,"approve",new AbortController().signal)).kind).toBe("invalid")
    expect(attempts).toBe(0)
  })
  it("requires idempotency and version, and checks owner-confirmed result",async()=>{
    const snapshot=item()
    let request: {url:string;options:RequestInit}|undefined
    globalThis.fetch=async(url,options)=>{
      request={url:String(url),options:options!}
      return new Response(JSON.stringify({...snapshot,status:"approved",version:2,
        allowed_actions:[],resolved_by_user_uuid:approval,issued_session_uuid:project}),{status:200})
    }
    const result=await resolveProjectApproval(parseApproval(snapshot,project)!,"approve",new AbortController().signal)
    expect(result.kind).toBe("confirmed")
    const headers=request!.options.headers as Record<string,string>
    expect(headers["Operation-UUID"]).toBe(headers["Idempotency-Key"])
    expect(request!.options.credentials).toBe("same-origin")
    expect(JSON.parse(request!.options.body as string).expected_approval_version).toBe(1)
  })
  it("handles 409 revision conflict without pretending success",async()=>{
    globalThis.fetch=async()=>new Response(JSON.stringify({error:{code:"APPROVAL_REVISION_CONFLICT"}}),{status:409})
    expect((await resolveProjectApproval(parseApproval(item(),project)!,"deny",new AbortController().signal)).kind).toBe("conflict")
  })
  it("marks transport failure uncertain and never replays write",async()=>{
    let calls=0
    globalThis.fetch=async()=>{calls++;throw new TypeError("network")}
    expect((await resolveProjectApproval(parseApproval(item(),project)!,"deny",new AbortController().signal)).kind).toBe("uncertain")
    expect(calls).toBe(1)
  })
})

describe("committed approval receipt invariants",()=>{
  it("rejects impossible pending/resolved states and self-issued child sessions",()=>{
    for(const bad of [
      {...item(),resolved_by_user_uuid:approval},
      {...item(),issued_session_uuid:project},
      {...item(),status:'approved',allowed_actions:[],resolved_by_user_uuid:approval},
      {...item(),status:'rejected',allowed_actions:[],resolved_by_user_uuid:approval,issued_session_uuid:project},
      {...item(),status:'approved',allowed_actions:[],resolved_by_user_uuid:user,issued_session_uuid:project},
      {...item(),status:'approved',allowed_actions:[],resolved_by_user_uuid:approval,issued_session_uuid:session},
    ])expect(parseApproval(bad,project)).toBeNull()
  })
  it("rejects a reserved Files scope pointing at another Project",()=>{
    const raw=item();raw.requested_resources[0]!.resource.id='project-path-v1:'+session+':'+('b'.repeat(64))
    expect(parseApproval(raw,project)).toBeNull()
  })
  it("rejects scope substitution in a pending dialog and skipped receipt revisions",async()=>{
    const selected=parseApproval(item(),project)!
    const changed={...selected,requested_resources:[{...selected.requested_resources[0]!,resource:{kind:'workspace_path',id:'other.md'}}]}
    expect(approvalStillCurrentForActor(selected,[changed],'approve',project,approval)).toBe(false)
    globalThis.fetch=async()=>new Response(JSON.stringify({...selected,status:'approved',version:3,allowed_actions:[],resolved_by_user_uuid:approval,issued_session_uuid:project}),{status:200})
    expect((await resolveProjectApproval(selected,'approve',new AbortController().signal)).kind).toBe('uncertain')
  })
})
