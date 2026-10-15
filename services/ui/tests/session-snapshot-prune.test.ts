import {describe,expect,it} from "bun:test"
import {pruneElapsedSessionRows} from "../src/features/agent-sessions/model/prune-current-snapshot"
import type {CurrentAgentSession} from "../src/features/agent-sessions/api/current-sessions"

const project="11111111-1111-4111-8111-111111111111"
const actor="22222222-2222-4222-8222-222222222222"
const origin=1_798_000_000_000
function record(id:string,status:CurrentAgentSession["status"],deadline:number):CurrentAgentSession{
  return {
    session_uuid:id,project_uuid:project,created_by_user_uuid:actor,
    revision:3,status,is_elevated:false,elevation_policy:"requestable",
    hard_expires_at:new Date(deadline).toISOString(),
    operations:["files.read"],resources:[],
    allowed_actions:status==="active"?["revoke"]:[],
  }
}
describe("independently expiring current AgentSession snapshots",()=>{
  it("retires one elapsed active item but retains unrelated rows/history",()=>{
    const first=record("a","active",origin+1000)
    const second=record("b","active",origin+60000)
    const historical=record("c","revoked",origin-1000)
    const data=[first,second,historical]
    const aged=pruneElapsedSessionRows(data,origin+2000)
    expect(aged).toEqual({items:[second,historical],removed:1})
    expect(data).toEqual([first,second,historical])
    expect(aged.items[0]?.status).toBe("active")
  })
  it("does not restore an elapsed session if the wall clock moves backward",()=>{
    const expired=record("a","active",origin+1000)
    const stillCurrent=record("b","active",origin+30000)
    const cutoff=Math.max(origin-4000,origin+1000)
    expect(pruneElapsedSessionRows([expired,stillCurrent],cutoff)).toEqual({
      items:[stillCurrent],removed:1,
    })
    expect(pruneElapsedSessionRows([expired,stillCurrent],origin+90000)).toEqual({items:[],removed:2})
  })
  it("treats malformed deadline and invalid clock conservatively",()=>{
    const item=record("a","active",origin+2000)
    const history=record("h","expired",origin-90000)
    expect(pruneElapsedSessionRows([{...item,hard_expires_at:"?"},history],origin)).toEqual({
      items:[history],removed:1,
    })
    expect(pruneElapsedSessionRows([item,history],Number.NaN)).toEqual({items:[],removed:2})
  })
})
