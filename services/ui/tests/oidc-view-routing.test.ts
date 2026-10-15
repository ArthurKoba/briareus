import {describe,expect,it} from "bun:test"
import {OIDC_PRESENTATION_PAGES,resolveOidcView,countPresentableAgentSessionProjects,preferredAgentSessionProjectId,reconcileAgentSessionProjectId} from "../src/features/platform/model/oidc-view-routing"

describe("OIDC presentation-only routing",()=>{
  it("does not unlock routes on provider identity alone",()=>{
    for(const path of ["#platform/mcp/files/settings","#platform/projects","#platform/sessions"]){
      expect(resolveOidcView(path,false)).toBe("home")
    }
  })
  it("preserves typed deep-links after positive verified User",()=>{
    expect(resolveOidcView("#platform/mcp/files/settings",true)).toBe("mcp")
    expect(resolveOidcView("#platform/sessions",true)).toBe("sessions")
    expect(resolveOidcView("#platform/projects",true)).toBe("projects")
    expect(OIDC_PRESENTATION_PAGES).toContain("settings")
  })
  it("shows MVP Session navigation only for owner-verified Project resource/approver scopes",()=>{
    expect(countPresentableAgentSessionProjects([])).toBe(0)
    expect(countPresentableAgentSessionProjects([{permissions:[]}])).toBe(0)
    expect(countPresentableAgentSessionProjects([
      {permissions:["use_resources"]},
      {permissions:["approve_agent_session"]},
      {permissions:["use_resources","approve_agent_session"]},
      {permissions:["admin"]},
    ])).toBe(3)
    // This count only controls a visible link; individual POSTs must
    // still re-prove the exact Project and current server permission.
    expect(resolveOidcView("#platform/sessions",false)).toBe("home")
  })
  it("preselects an actionable Project rather than a permissionless first entry",()=>{
    expect(preferredAgentSessionProjectId([])).toBeNull()
    const projects=[
      {id:"read-only",permissions:[]},
      {id:"approver",permissions:["approve_agent_session"]},
      {id:"resource",permissions:["use_resources"]},
    ]
    expect(preferredAgentSessionProjectId(projects)).toBe("resource")
    expect(preferredAgentSessionProjectId(projects.slice(0,2))).toBe("approver")
    expect(preferredAgentSessionProjectId(projects.slice(0,1))).toBe("read-only")
    // Selection never assigns a missing permission.
    expect(countPresentableAgentSessionProjects(projects.slice(0,1))).toBe(0)
  })
  it("retains selected Project through route remounts but resets revoked/changed ownership",()=>{
    const projects=[
      {id:"project-1",permissions:["use_resources"]},
      {id:"project-2",permissions:["approve_agent_session"]},
      {id:"project-3",permissions:[]},
    ]
    expect(reconcileAgentSessionProjectId(null,projects)).toBe("project-1")
    expect(reconcileAgentSessionProjectId("project-2",projects)).toBe("project-2")
    expect(reconcileAgentSessionProjectId("project-2",projects.slice(0,1))).toBe("project-1")
    expect(reconcileAgentSessionProjectId("project-2",[
      {id:"project-1",permissions:["use_resources"]},
      {id:"project-2",permissions:[]},
    ])).toBe("project-1")
    expect(reconcileAgentSessionProjectId("project-2",[])).toBeNull()
    // Caller must supply null on a changed principal, never reuse an ID.
    expect(reconcileAgentSessionProjectId(null,projects.slice(1))).toBe("project-2")
  })
  it("rejects unknown and historical routes",()=>{
    for(const hash of ["","#old/admin","#platform/not-a-page","#/admin"]){
      expect(resolveOidcView(hash,true)).toBe("home")
    }
  })
})
