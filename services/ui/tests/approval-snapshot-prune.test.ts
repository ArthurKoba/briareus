import {describe,expect,it} from "bun:test"
import type {ApprovalRecord} from "../src/features/approvals/types"
import {pruneElapsedApprovalRows} from "../src/features/approvals/model/prune-current-snapshot"

const now=1_798_000_000_000
const skeleton:ApprovalRecord={
  id:"11111111-1111-4111-8111-111111111111",
  project_uuid:"22222222-2222-4222-8222-222222222222",
  agent_session_uuid:"33333333-3333-4333-8333-333333333333",
  requested_by_user_uuid:"44444444-4444-4444-8444-444444444444",
  status:"pending",version:1,requested_operations:["files.read"],
  requested_resources:[],requested_expires_at:new Date(now+1_000).toISOString(),
  resolved_by_user_uuid:null,issued_session_uuid:null,allowed_actions:["approve","deny"],
}
describe("independent approval decision deadlines",()=>{
  it("retains another actionable request and resolved request when the earliest expires",()=>{
    const next={...skeleton,id:"55555555-5555-4555-8555-555555555555",
      requested_expires_at:new Date(now+100_000).toISOString()}
    const resolved={...skeleton,id:"66666666-6666-4666-8666-666666666666",
      status:"rejected" as const,version:2,allowed_actions:[] as ApprovalRecord["allowed_actions"],
      resolved_by_user_uuid:"77777777-7777-4777-8777-777777777777"}
    const all=[skeleton,next,resolved]
    expect(pruneElapsedApprovalRows(all,now+1001)).toEqual({items:[next,resolved],removed:1})
    expect(all).toEqual([skeleton,next,resolved])
  })
  it("leaves a pending non-actionable observation while expiring active commands",()=>{
    const passive={...skeleton,id:"88888888-8888-4888-8888-888888888888",
      allowed_actions:[] as ApprovalRecord["allowed_actions"]}
    expect(pruneElapsedApprovalRows([skeleton,passive],now+1002)).toEqual({
      items:[passive],removed:1,
    })
  })
  it("refuses impossible clocks rather than displaying potentially live commands",()=>{
    expect(pruneElapsedApprovalRows([skeleton],Number.NaN)).toEqual({items:[],removed:1})
    expect(pruneElapsedApprovalRows([skeleton],now+500)).toEqual({items:[skeleton],removed:0})
    expect(pruneElapsedApprovalRows([skeleton],now+1001)).toEqual({items:[],removed:1})
    expect(pruneElapsedApprovalRows([{...skeleton,requested_expires_at:"bogus"}],now)).toEqual({items:[],removed:1})
  })
})
