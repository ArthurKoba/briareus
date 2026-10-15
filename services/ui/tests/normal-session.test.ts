import { afterEach, describe, expect, it } from "bun:test"
import { openNormalSession, parseNormalSession } from "../src/features/agent-sessions/api/open-normal"

const project = "11111111-1111-4111-8111-111111111111"
const session = "22222222-2222-4222-8222-222222222222"
const fixture = () => ({
  session_uuid: session, project_uuid: project, revision: 1,
  status: "active", is_elevated: false, elevation_policy: "requestable",
  hard_expires_at: new Date(Date.now() + 30 * 60_000).toISOString(),
  operations: ["files.read", "project.metadata.read"], resources: [],
})
const originalFetch = globalThis.fetch
afterEach(() => { globalThis.fetch = originalFetch })

describe("normal AgentSession owner contract", () => {
  it("accepts a fresh project-bound exactly-normal snapshot", () => {
    expect(parseNormalSession(fixture(), project, "requestable")?.revision).toBe(1)
  })
  it("rejects a different Project, privilege escalation, and altered revision", () => {
    expect(parseNormalSession({ ...fixture(), project_uuid: session }, project, "requestable")).toBeNull()
    expect(parseNormalSession({ ...fixture(), is_elevated: true }, project, "requestable")).toBeNull()
    expect(parseNormalSession({ ...fixture(), revision: 2 }, project, "requestable")).toBeNull()
    expect(parseNormalSession({ ...fixture(), operations: ["files.write"] }, project, "requestable")).toBeNull()
  })
  it("rejects expired, unbounded, and timezone-less server expiry", () => {
    expect(parseNormalSession({ ...fixture(), hard_expires_at: new Date(Date.now() - 1000).toISOString() }, project, "requestable")).toBeNull()
    expect(parseNormalSession({ ...fixture(), hard_expires_at: new Date(Date.now() + 25 * 60 * 60_000).toISOString() }, project, "requestable")).toBeNull()
    expect(parseNormalSession({ ...fixture(), hard_expires_at: "2026-10-14T08:00:00" }, project, "requestable")).toBeNull()
  })
  it("requires a canonical same-origin idempotent POST", async () => {
    let call: {url: string; options: RequestInit} | null = null
    globalThis.fetch = async (url, options) => {
      call = {url: String(url), options: options!}
      return new Response(JSON.stringify(fixture()), {status: 201})
    }
    const response = await openNormalSession(project, "requestable", "Local UI", new AbortController().signal)
    expect(response.kind).toBe("created")
    expect(call!.url).toBe("/api/v1/agent-sessions")
    expect(call!.options.credentials).toBe("same-origin")
    expect(call!.options.redirect).toBe("error")
    const headers = call!.options.headers as Record<string, string>
    expect(headers["Operation-UUID"]).toBe(headers["Idempotency-Key"])
    expect(JSON.parse(call!.options.body as string).label).toBe("Local UI")
  })
  it("never sends invalid labels to Backend", async () => {
    let invoked = false
    globalThis.fetch = async () => { invoked = true; throw new Error("must not fetch") }
    const response = await openNormalSession(project, "fixed", "a\nnewline", new AbortController().signal)
    expect(response.kind).toBe("invalid")
    expect(invoked).toBe(false)
  })
  it.each([
    [401, "unauthorized"],
    [403, "forbidden"],
    [409, "conflict"],
    [422, "invalid"],
    [503, "uncertain"],
  ] as const)("maps HTTP %d to %s without inventing success", async (status, expected) => {
    globalThis.fetch = async () => new Response(JSON.stringify({error: {code: "NOT_ALLOWED"}}), {status})
    expect((await openNormalSession(project, "fixed", "", new AbortController().signal)).kind).toBe(expected)
  })
  it("returns uncertain if success DTO was tampered", async () => {
    globalThis.fetch = async () => new Response(JSON.stringify({...fixture(), status:"revoked"}), {status:201})
    expect((await openNormalSession(project, "requestable", "", new AbortController().signal)).kind).toBe("uncertain")
  })
  it("does not automatically replay a POST after transport failure", async () => {
    let calls = 0
    globalThis.fetch = async () => {calls++; throw new TypeError("network")}
    expect((await openNormalSession(project, "requestable", "", new AbortController().signal)).kind).toBe("uncertain")
    expect(calls).toBe(1)
  })
})

describe("preserved session creation intents",()=>{
  it("replays exact bytes and operation key after a lost reply without creating another intent",async()=>{
    const {prepareNormalSessionOpen,executeNormalSessionOpen}=await import('../src/features/agent-sessions/api/open-normal')
    const prepared=prepareNormalSessionOpen(project,'requestable','original')
    if(prepared.kind!=='prepared')throw new Error('preparation failed')
    const requests:RequestInit[]=[]
    globalThis.fetch=async(_url,options)=>{
      requests.push(options!)
      if(requests.length===1)throw new TypeError('lost reply after owner commit')
      return new Response(JSON.stringify(fixture()),{status:201})
    }
    expect((await executeNormalSessionOpen(prepared.command,new AbortController().signal)).kind).toBe('uncertain')
    expect((await executeNormalSessionOpen(prepared.command,new AbortController().signal)).kind).toBe('created')
    expect(requests.length).toBe(2)
    expect(requests[0]!.body).toBe(requests[1]!.body)
    expect(requests[0]!.headers).toEqual(requests[1]!.headers)
    expect(Object.isFrozen(prepared.command)).toBe(true)
  })
  it("preserves one unresolved intent across route readers and rejects replacement",async()=>{
    const {createSessionOpenRecovery,sessionOpenOwnerKey}=await import('../src/features/agent-sessions/model/open-recovery')
    const journal=createSessionOpenRecovery()
    const owner=sessionOpenOwnerKey('https://identity.example.invalid','sub','panel',session)
    const first=journal.reserve(owner,project,'fixed','original')
    if(first.kind!=='reserved')throw new Error('reservation failed')
    expect(journal.get(owner,project)).toBe(first.entry)
    expect(journal.reserve(owner,project,'requestable','changed').kind).toBe('conflict')
    expect(journal.get(owner,project)?.command.label).toBe('original')
    journal.complete(first.entry)
    const second=journal.reserve(owner,project,'requestable','new')
    if(second.kind!=='reserved')throw new Error('reservation failed')
    expect(second.entry.command.operation).not.toBe(first.entry.command.operation)
    journal.complete(first.entry)
    expect(journal.isCurrent(second.entry)).toBe(true)
  })
  it("isolates identity/Project and destroys retained intents on logout",async()=>{
    const {createSessionOpenRecovery,sessionOpenOwnerKey}=await import('../src/features/agent-sessions/model/open-recovery')
    const journal=createSessionOpenRecovery(),other='33333333-3333-4333-8333-333333333333'
    const owner=sessionOpenOwnerKey('https://identity.example.invalid','one','panel',session)
    const next=sessionOpenOwnerKey('https://identity.example.invalid','two','panel',session)
    const first=journal.reserve(owner,project,'fixed','')
    if(first.kind!=='reserved')throw new Error('reservation failed')
    expect(journal.get(next,project)).toBeNull()
    expect(journal.get(owner,other)).toBeNull()
    journal.retainOwner(next)
    expect(journal.isCurrent(first.entry)).toBe(false)
    journal.reserve(next,project,'fixed','')
    journal.clear()
    expect(journal.get(next,project)).toBeNull()
  })
  it("refuses a reconstructed/mutated command and sends nothing after preflight cancellation",async()=>{
    const {prepareNormalSessionOpen,executeNormalSessionOpen}=await import('../src/features/agent-sessions/api/open-normal')
    const prepared=prepareNormalSessionOpen(project,'requestable','')
    if(prepared.kind!=='prepared')throw new Error('preparation failed')
    let calls=0;globalThis.fetch=async()=>{calls++;throw new Error('unexpected')}
    expect((await executeNormalSessionOpen({...prepared.command,body:'{}'},new AbortController().signal)).kind).toBe('invalid')
    const request=new AbortController();request.abort()
    expect((await executeNormalSessionOpen(prepared.command,request.signal)).kind).toBe('unavailable')
    expect(calls).toBe(0)
  })
})

describe("bounded creation recovery lifetime",()=>{
  it("will not replay an old intent after the normal session lifetime",async()=>{
    const {prepareNormalSessionOpen,executeNormalSessionOpen}=await import('../src/features/agent-sessions/api/open-normal')
    const originalNow=Date.now,now=Date.now()
    const prepared=prepareNormalSessionOpen(project,'requestable','')
    if(prepared.kind!=='prepared')throw new Error('preparation failed')
    let calls=0;globalThis.fetch=async()=>{calls++;throw new Error('unexpected')}
    try{
      Date.now=()=>now+25*60*60_000
      expect(await executeNormalSessionOpen(prepared.command,new AbortController().signal))
        .toEqual({kind:'unavailable',code:'SESSION_RECOVERY_WINDOW_ELAPSED'})
      expect(calls).toBe(0)
    }finally{Date.now=originalNow}
  })
})

describe("creation command lifecycle",()=>{
  it("cannot revive an elapsed intent after the wall clock is restored",async()=>{
    const {prepareNormalSessionOpen,executeNormalSessionOpen}=await import('../src/features/agent-sessions/api/open-normal')
    const original=Date.now,now=Date.now(),p=prepareNormalSessionOpen(project,'fixed','')
    if(p.kind!=='prepared')throw new Error('prepare')
    let requests=0;globalThis.fetch=async()=>{requests++;throw new Error('unexpected')}
    try{
      Date.now=()=>now+25*3600_000
      expect((await executeNormalSessionOpen(p.command,new AbortController().signal)).kind).toBe('unavailable')
      Date.now=()=>now
      expect((await executeNormalSessionOpen(p.command,new AbortController().signal)).kind).toBe('unavailable')
      expect(requests).toBe(0)
    }finally{Date.now=original}
  })
  it("uses a snapshot of the actor and preserves an interrupted dispatch for the original owner",async()=>{
    const {openVerifiedNormalSession}=await import('../src/features/agent-sessions/model/open-verified')
    const {createSessionOpenRecovery}=await import('../src/features/agent-sessions/model/open-recovery')
    for(const dispatched of [false,true]){
      const journal=createSessionOpenRecovery()
      const context={ownerKey:'owner',actorId:session,projectId:project,canOpen:true,proofExpiresAt:new Date(Date.now()+20_000).toISOString()}
      let calls=0
      globalThis.fetch=async()=>{calls++;context.actorId=project;return new Response(JSON.stringify(fixture()),{status:201})}
      const result=await openVerifiedNormalSession({journal,saved:null,policy:'requestable',label:'original',signal:new AbortController().signal,context:()=>context,verify:async()=>{
        if(!dispatched)context.actorId=project
        return 'authorized'
      }})
      expect(result.kind).toBe(dispatched?'uncertain':'cancelled')
      expect(calls).toBe(dispatched?1:0)
      expect(journal.get('owner',project)!==null).toBe(dispatched)
    }
  })
  it("revalidates the same saved request, and retry denial never erases its uncertain result",async()=>{
    const {openVerifiedNormalSession}=await import('../src/features/agent-sessions/model/open-verified')
    const {createSessionOpenRecovery}=await import('../src/features/agent-sessions/model/open-recovery')
    const journal=createSessionOpenRecovery(),context={ownerKey:'owner',actorId:session,projectId:project,canOpen:true,proofExpiresAt:new Date(Date.now()+20_000).toISOString()}
    const options={journal,policy:'requestable' as const,label:'original',signal:new AbortController().signal,context:()=>context,verify:async()=> 'authorized' as const}
    const requests:RequestInit[]=[]
    globalThis.fetch=async(_url,init)=>{requests.push(init!);return new Response('{}',{status:503})}
    expect((await openVerifiedNormalSession({...options,saved:null})).kind).toBe('uncertain')
    const saved=journal.get('owner',project)!
    expect(saved.command.label).toBe('original')
    expect((await openVerifiedNormalSession({...options,saved,verify:async()=> 'forbidden'})).kind).toBe('forbidden')
    expect(journal.get('owner',project)).toBe(saved)
    globalThis.fetch=async(_url,init)=>{requests.push(init!);return new Response(JSON.stringify(fixture()),{status:201})}
    expect((await openVerifiedNormalSession({...options,saved,label:'ignored'})).kind).toBe('created')
    expect(requests[0]!.body).toBe(requests[1]!.body)
    expect(requests[0]!.headers).toEqual(requests[1]!.headers)
    expect(journal.get('owner',project)).toBeNull()
  })
  it("does not keep a new intent on explicit initial owner refusal",async()=>{
    const {openVerifiedNormalSession}=await import('../src/features/agent-sessions/model/open-verified')
    const {createSessionOpenRecovery}=await import('../src/features/agent-sessions/model/open-recovery')
    const journal=createSessionOpenRecovery(),context={ownerKey:'owner',actorId:session,projectId:project,canOpen:true,proofExpiresAt:new Date(Date.now()+20_000).toISOString()}
    globalThis.fetch=async()=>new Response('{}',{status:403})
    expect((await openVerifiedNormalSession({journal,saved:null,policy:'requestable',label:'',signal:new AbortController().signal,context:()=>context,verify:async()=> 'authorized'})).kind).toBe('forbidden')
    expect(journal.get('owner',project)).toBeNull()
  })
})

describe("monotonic recovery deadline",()=>{
  it("cannot extend a prepared intent by moving the wall clock backward",async()=>{
    const {spyOn}=await import('bun:test')
    const {prepareNormalSessionOpen,normalSessionReplayRemaining,executeNormalSessionOpen}=await import('../src/features/agent-sessions/api/open-normal')
    const now=Date.now();let clock=100
    const wall=spyOn(Date,'now').mockReturnValue(now)
    const monotonic=spyOn(performance,'now').mockImplementation(()=>clock)
    try{
      const p=prepareNormalSessionOpen(project,'fixed','')
      if(p.kind!=='prepared')throw new Error('prepare')
      wall.mockReturnValue(now-3600_000);clock+=25*3600_000
      expect(normalSessionReplayRemaining(p.command)).toBe(0)
      let calls=0;globalThis.fetch=async()=>{calls++;throw new Error('unexpected')}
      expect((await executeNormalSessionOpen(p.command,new AbortController().signal)).kind).toBe('unavailable')
      expect(calls).toBe(0)
    }finally{monotonic.mockRestore();wall.mockRestore()}
  })
})
