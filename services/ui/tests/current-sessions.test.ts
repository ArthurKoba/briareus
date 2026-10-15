import {afterEach,describe,expect,it} from "bun:test"
import {
  listCurrentSessions,parseCurrentSession,revokeCurrentSession,
} from "../src/features/agent-sessions/api/current-sessions"

const project="11111111-1111-4111-8111-111111111111"
const actor="22222222-2222-4222-8222-222222222222"
const other="33333333-3333-4333-8333-333333333333"
const session="44444444-4444-4444-8444-444444444444"
const active=()=>({
  session_uuid:session,project_uuid:project,created_by_user_uuid:other,
  revision:4,status:"active",is_elevated:false,elevation_policy:"requestable",
  hard_expires_at:new Date(Date.now()+600_000).toISOString(),
  operations:["files.read","project.metadata.read"],resources:[],
  allowed_actions:["revoke"],
})
const realFetch=globalThis.fetch
afterEach(()=>{globalThis.fetch=realFetch})

describe("server-current scoped AgentSession list and revoke",()=>{
  it("accepts an owner-bounded current session with approver right",()=>{
    expect(parseCurrentSession(active(),project,actor,true)?.revision).toBe(4)
    expect(parseCurrentSession({...active(),allowed_actions:[]},project,actor,true)?.allowed_actions).toEqual([])
  })
  it("rejects cross-project and noncreator view without approver right",()=>{
    expect(parseCurrentSession({...active(),project_uuid:other},project,actor,true)).toBeNull()
    expect(parseCurrentSession(active(),project,actor,false)).toBeNull()
    expect(parseCurrentSession({...active(),allowed_actions:[]},project,actor,false)).toBeNull()
    expect(parseCurrentSession({...active(),created_by_user_uuid:actor,allowed_actions:[]},project,actor,false)?.created_by_user_uuid).toBe(actor)
  })
  it("rejects inconsistent statuses, actions and expiry",()=>{
    for(const invalid of [
      {...active(),revision:0},
      {...active(),status:"approved"},
      {...active(),status:"revoked",allowed_actions:["revoke"]},
      {...active(),status:"active",hard_expires_at:new Date(Date.now()-1000).toISOString()},
      {...active(),status:"expired",hard_expires_at:new Date(Date.now()+100000).toISOString()},
      {...active(),hard_expires_at:"2026-10-14T19:00:00"},
      {...active(),allowed_actions:["approve"]},
      {...active(),operations:["files.read","files.read"]},
      {...active(),operations:["super-admin"]},
    ])expect(parseCurrentSession(invalid,project,actor,true)).toBeNull()
  })
  it("rejects resource scopes with unspecified effects",()=>{
    expect(parseCurrentSession({...active(),resources:[{
      hand:"files",tool:"read_file",action:"terminal.execute",
      resource:{kind:"workspace_file",id:"a.txt"},
    }]},project,actor,true)).toBeNull()
    expect(parseCurrentSession({...active(),resources:[{
      hand:"unknown",tool:"read_file",action:"files.read",
      resource:{kind:"workspace_file",id:"a.txt"},
    }]},project,actor,true)).toBeNull()
  })
  it("rejects a semantically impossible Hand effect despite known operation name",()=>{
    const valid={hand:"files",tool:"read_file",action:"files.read",
      resource:{kind:"workspace_path",id:"src/file.txt"}}
    expect(parseCurrentSession({...active(),resources:[valid]},project,actor,true)?.resources.length).toBe(1)
    expect(parseCurrentSession({...active(),resources:[{...valid,hand:"terminal"}]},project,actor,true)).toBeNull()
    expect(parseCurrentSession({...active(),resources:[{...valid,resource:{kind:"origin",id:"https://test.invalid"}}]},project,actor,true)).toBeNull()
    expect(parseCurrentSession({...active(),resources:[valid,valid]},project,actor,true)).toBeNull()
  })
  it("accepts exact Project-scoped GET and rejects duplicate IDs",async()=>{
    let request: {url:string;init:RequestInit}|undefined
    globalThis.fetch=async(url,init)=>{
      request={url:String(url),init:init!}
      return new Response(JSON.stringify({items:[active()]}),{status:200})
    }
    expect((await listCurrentSessions(project,actor,true,new AbortController().signal)).kind).toBe("ready")
    expect(request?.url).toBe("/api/v1/agent-sessions?project_uuid="+project)
    expect(request?.init.credentials).toBe("same-origin")
    expect(request?.init.redirect).toBe("error")
    globalThis.fetch=async()=>new Response(JSON.stringify({items:[active(),active()]}),{status:200})
    expect((await listCurrentSessions(project,actor,true,new AbortController().signal)).kind).toBe("invalid")
  })
  it.each([[401,"unauthorized"],[403,"forbidden"],[503,"unavailable"]] as const)(
    "GET %d remains %s",async(status,expected)=>{
      globalThis.fetch=async()=>new Response(JSON.stringify({error:{code:"NO_SCOPE"}}),{status})
      expect((await listCurrentSessions(project,actor,true,new AbortController().signal)).kind).toBe(expected)
    },
  )
  it("cannot revoke unless the exact current server row allows it",async()=>{
    let count=0
    globalThis.fetch=async()=>{count++;throw new Error("should not call")}
    const row=parseCurrentSession({...active(),allowed_actions:[]},project,actor,true)!
    expect((await revokeCurrentSession(row,new AbortController().signal)).kind).toBe("invalid")
    expect(count).toBe(0)
  })
  it("sends a single idempotent version-fenced revoke, accepts higher revision only",async()=>{
    let request:{url:string;init:RequestInit}|undefined
    globalThis.fetch=async(url,init)=>{
      request={url:String(url),init:init!}
      return new Response(JSON.stringify({
        session_uuid:session,project_uuid:project,status:"revoked",revision:5,
      }),{status:200})
    }
    const item=parseCurrentSession(active(),project,actor,true)!
    expect((await revokeCurrentSession(item,new AbortController().signal)).kind).toBe("confirmed")
    expect(request!.url).toBe("/api/v1/agent-sessions/"+session+"/revoke")
    const headers=request!.init.headers as Record<string,string>
    expect(headers["Operation-UUID"]).toBe(headers["Idempotency-Key"])
    expect(request!.init.credentials).toBe("same-origin")
    expect(JSON.parse(request!.init.body as string).expected_grant_revision).toBe(4)
    expect(JSON.parse(request!.init.body as string).project_uuid).toBe(project)
  })
  it("rejects false revoke proof and preserves 409 conflict",async()=>{
    const item=parseCurrentSession(active(),project,actor,true)!
    globalThis.fetch=async()=>new Response(JSON.stringify({
      session_uuid:session,project_uuid:project,status:"revoked",revision:4,
    }),{status:200})
    expect((await revokeCurrentSession(item,new AbortController().signal)).kind).toBe("uncertain")
    globalThis.fetch=async()=>new Response(JSON.stringify({error:{code:"REVISION_CONFLICT"}}),{status:409})
    expect((await revokeCurrentSession(item,new AbortController().signal)).kind).toBe("conflict")
  })
  it("does not replay ambiguous POST after a lost connection",async()=>{
    let calls=0
    globalThis.fetch=async()=>{calls++;throw new TypeError("connection")}
    const item=parseCurrentSession(active(),project,actor,true)!
    expect((await revokeCurrentSession(item,new AbortController().signal)).kind).toBe("uncertain")
    expect(calls).toBe(1)
  })
})

describe("individual current AgentSession",()=>{
  it("uses the exact scoped single-session GET and rejects a different session",async()=>{
    const {readCurrentSession}=await import("../src/features/agent-sessions/api/current-sessions")
    let observed=""
    globalThis.fetch=async(url,options)=>{
      observed=String(url)
      expect(options?.credentials).toBe("same-origin")
      expect(options?.redirect).toBe("error")
      return new Response(JSON.stringify(active()),{status:200})
    }
    expect((await readCurrentSession(project,session,actor,true,new AbortController().signal)).kind).toBe("ready")
    expect(observed).toBe("/api/v1/agent-sessions/"+session+"?project_uuid="+project)
    globalThis.fetch=async()=>new Response(JSON.stringify({...active(),session_uuid:other}),{status:200})
    expect((await readCurrentSession(project,session,actor,true,new AbortController().signal)).kind).toBe("invalid")
  })
  it("does not claim revocation from missing endpoint, foreign scope, invalid body or cancellation",async()=>{
    const {readCurrentSession}=await import("../src/features/agent-sessions/api/current-sessions")
    for(const [value,status,kind] of [[{},404,"unavailable"],[{...active(),project_uuid:other},200,"invalid"],[{items:[active()]},200,"invalid"]] as const){
      globalThis.fetch=async()=>new Response(JSON.stringify(value),{status})
      expect((await readCurrentSession(project,session,actor,true,new AbortController().signal)).kind).toBe(kind)
    }
    let calls=0;globalThis.fetch=async()=>{calls++;throw new Error("unexpected")}
    const request=new AbortController();request.abort()
    expect((await readCurrentSession(project,session,actor,true,request.signal)).kind).toBe("unavailable")
    expect(calls).toBe(0)
  })
})

describe("Project-bound Files resources in session responses",()=>{
  it("rejects a current-session row containing another Project compact scope",()=>{
    const resource={hand:'files',tool:'read_file',action:'files.read',resource:{kind:'workspace_path',id:'project-path-v1:'+project+':'+('d'.repeat(64))}}
    expect(parseCurrentSession({...active(),resources:[resource]},project,actor,true)?.resources).toHaveLength(1)
    expect(parseCurrentSession({...active(),resources:[{...resource,resource:{...resource.resource,id:resource.resource.id.replace(project,other)}}]},project,actor,true)).toBeNull()
  })
})

describe("exact lookup missing-route distinction",()=>{
  it("exposes semantic not-found only for the scoped owner code and HTTP404 pair",async()=>{
    const {readCurrentSession}=await import('../src/features/agent-sessions/api/current-sessions')
    for(const [status,code,kind] of [[404,'AGENT_SESSION_NOT_FOUND','not_found'],[404,'UNKNOWN','unavailable'],[503,'AGENT_SESSION_NOT_FOUND','unavailable']] as const){
      globalThis.fetch=async()=>new Response(JSON.stringify({error:{code}}),{status})
      expect((await readCurrentSession(project,session,actor,true,new AbortController().signal)).kind).toBe(kind)
    }
  })
  it("validates direct lookup IDs before any owner request",async()=>{
    const {isCurrentSessionId,readCurrentSession}=await import('../src/features/agent-sessions/api/current-sessions')
    expect(isCurrentSessionId(session)).toBe(true)
    let calls=0;globalThis.fetch=async()=>{calls++;throw new Error('unexpected')}
    for(const id of ['../session','https://other.invalid',session.toUpperCase(),session+':secret','']){
      if(id===session)continue
      expect(isCurrentSessionId(id)).toBe(false)
      expect((await readCurrentSession(project,id,actor,true,new AbortController().signal)).kind).toBe('invalid')
    }
    expect(calls).toBe(0)
  })
})

describe("Files scope display and cancelled inventory",()=>{
  it("never treats an action-only normal AgentSession as an exact Files read",async()=>{
    const {filesReadScopes}=await import('../src/features/agent-sessions/model/files-read-scopes')
    const normal=parseCurrentSession({
      session_uuid:session,project_uuid:project,created_by_user_uuid:actor,revision:1,
      status:'active',is_elevated:false,elevation_policy:'requestable',
      hard_expires_at:new Date(Date.now()+60_000).toISOString(),
      operations:['files.read','project.metadata.read'],resources:[],allowed_actions:[],
    },project,actor,false)
    expect(normal).not.toBeNull()
    expect(filesReadScopes([normal!],project)).toEqual([])
    const scoped={...normal!,resources:[{hand:'files',tool:'read_file',action:'files.read',resource:{kind:'workspace_path',id:'README.md'}}]}
    expect(filesReadScopes([scoped],project)).toEqual([{
      sessionId:session,revision:1,expiresAt:scoped.hard_expires_at,selector:'README.md',
    }])
    expect(filesReadScopes([scoped],project,Date.parse(scoped.hard_expires_at)+1)).toEqual([])
    expect(filesReadScopes([scoped],'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa')).toEqual([])
    expect(filesReadScopes([{...scoped,status:'revoked'},scoped],project)).toHaveLength(1)
  })
  it("discards a cancelled inventory read even if fetch returns a late HTTP 200",async()=>{
    const {listCurrentSessions}=await import('../src/features/agent-sessions/api/current-sessions')
    const original=globalThis.fetch,controller=new AbortController()
    let count=0
    try{
      globalThis.fetch=async()=>{count++;controller.abort();return new Response(JSON.stringify({items:[]}),{status:200})}
      expect((await listCurrentSessions(project,actor,false,controller.signal)).kind).toBe('unavailable')
      expect(count).toBe(1)
      expect((await listCurrentSessions(project,actor,false,controller.signal)).kind).toBe('unavailable')
      expect(count).toBe(1)
    }finally{globalThis.fetch=original}
  })
})

describe("Files scope rows expire independently",()=>{
  it("retains unaffected sessions after the first expires",async()=>{
    const {retainUnexpiredFilesReadScopes}=await import('../src/features/agent-sessions/model/files-read-scopes')
    const now=Date.now()
    const older={sessionId:session,revision:1,selector:'old.txt',expiresAt:new Date(now+1000).toISOString()}
    const newer={sessionId:actor,revision:2,selector:'new.txt',expiresAt:new Date(now+60000).toISOString()}
    const list=[older,newer]
    expect(retainUnexpiredFilesReadScopes(list,now+1500)).toEqual([newer])
    expect(retainUnexpiredFilesReadScopes(list,now+60001)).toEqual([])
    expect(list).toEqual([older,newer])
  })
})

describe("bounded AgentSession inventory and lookup cancellation",()=>{
  it("rejects giant source lists before JSON parsing rather than displaying rows",async()=>{
    globalThis.fetch=async()=>new Response(JSON.stringify({
      items:[active()],
    }),{status:200,headers:{"Content-Length":"9000000"}})
    expect((await listCurrentSessions(project,actor,true,new AbortController().signal)).kind)
      .toBe("unavailable")
  })
  it("does not infer semantic not-found after a stalled 404 response was cancelled",async()=>{
    const {readCurrentSession}=await import('../src/features/agent-sessions/api/current-sessions')
    let cancelled=0
    const waiting=new ReadableStream<Uint8Array>({cancel(){cancelled++}})
    const request=new AbortController()
    globalThis.fetch=async()=>new Response(waiting,{status:404})
    const pending=readCurrentSession(project,session,actor,true,request.signal)
    setTimeout(()=>request.abort(),20)
    const result=await Promise.race([pending,new Promise<"hung">(resolve=>setTimeout(()=>resolve("hung"),300))])
    expect(result).toEqual({kind:"unavailable",code:"AGENT_SESSION_READ_CANCELLED"})
    expect(cancelled).toBe(1)
  })
})

describe("individual bounded AgentSession stream cancellation",()=>{
  it("distinguishes cancellation from Backend unavailability on a stalled successful point read",async()=>{
    const {readCurrentSession}=await import('../src/features/agent-sessions/api/current-sessions')
    let cancelled=0
    const waiting=new ReadableStream<Uint8Array>({cancel(){cancelled++}})
    const request=new AbortController()
    globalThis.fetch=async()=>new Response(waiting,{status:200})
    const pending=readCurrentSession(project,session,actor,true,request.signal)
    setTimeout(()=>request.abort(),20)
    const result=await Promise.race([pending,new Promise<"hung">(resolve=>setTimeout(()=>resolve("hung"),300))])
    expect(result).toEqual({kind:"unavailable",code:"AGENT_SESSION_READ_CANCELLED"})
    expect(cancelled).toBe(1)
  })
})
