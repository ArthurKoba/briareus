import {describe,expect,it} from "bun:test"
import {filesReadScopes,retainUnexpiredFilesReadScopes} from "../src/features/agent-sessions/model/files-read-scopes"
import type {CurrentAgentSession} from "../src/features/agent-sessions/api/current-sessions"

const project="11111111-1111-4111-8111-111111111111"
const actor="22222222-2222-4222-8222-222222222222"
const clock=1_798_000_000_000
function item(id:string,expiration:number):CurrentAgentSession{
  return {session_uuid:id,project_uuid:project,created_by_user_uuid:actor,
    revision:3,status:"active",is_elevated:true,elevation_policy:"requestable",
    hard_expires_at:new Date(expiration).toISOString(),operations:["files.read"],
    resources:[{hand:"files",tool:"read_file",action:"files.read",resource:{kind:"workspace_path",id:"one.txt"}}],
    allowed_actions:[],
  }
}
describe("Files read-only scope deadlines",()=>{
  it("ignores malformed or elapsed source sessions, not a Cedar grant",()=>{
    const normal=item(actor,clock+60_000)
    expect(filesReadScopes([normal],project,clock)).toHaveLength(1)
    expect(filesReadScopes([{...normal,hard_expires_at:"bogus"}],project,clock)).toEqual([])
    expect(filesReadScopes([normal],project,clock+90_000)).toEqual([])
  })
  it("monotonic earliest cutoff does not resurrect expired rows after clock rollback",()=>{
    const first=item(actor,clock+3_000)
    const other=item("33333333-3333-4333-8333-333333333333",clock+120_000)
    const scopes=filesReadScopes([first,other],project,clock)
    expect(scopes).toHaveLength(2)
    const fakeWallClock=clock-60_000
    const monotonicExpiredCutoff=Math.max(fakeWallClock,Date.parse(scopes[0]!.expiresAt))
    expect(retainUnexpiredFilesReadScopes(scopes,monotonicExpiredCutoff)).toEqual([scopes[1]])
    expect(retainUnexpiredFilesReadScopes(scopes,clock+121_000)).toEqual([])
    expect(scopes).toHaveLength(2)
  })
})
