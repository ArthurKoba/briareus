import {describe,expect,it} from "bun:test"
import {readFileSync,readdirSync,statSync} from "node:fs"
import {resolve,join} from "node:path"
import {CONTROL_PANEL_API_V1,CONTROL_PANEL_AUTH_API} from "../src/shared/config/control-panel-api"

const root=resolve(import.meta.dir,"../src")
function sourceFiles(directory:string):string[]{
  return readdirSync(directory).flatMap(name=>{
    const path=join(directory,name)
    if(statSync(path).isDirectory())return sourceFiles(path)
    return /\.(?:ts|vue)$/.test(name)?[path]:[]
  })
}

describe("one versioned Control Panel browser API namespace",()=>{
  it("pins API version/auth base without environment or provider-derived URL",()=>{
    expect(CONTROL_PANEL_API_V1).toBe("/api/v1")
    expect(CONTROL_PANEL_AUTH_API).toBe("/api/v1/auth")
  })
  it("keeps resource APIs beside auth under /api/v1, never nested within it",()=>{
    const clients=[
      "agent-sessions/api/open-normal.ts", "agent-sessions/api/current-sessions.ts",
      "approvals/api/control-panel.ts", "approvals/api/request-elevation.ts",
      "catalog/api/current-metadata.ts", "files-preview/api/files-content.ts",
    ]
    for(const path of clients){
      const code=readFileSync(resolve(root,"features",path),"utf8")
      expect(code).toContain("CONTROL_PANEL_API_V1")
      expect(code).not.toContain("CONTROL_PANEL_AUTH_API")
    }
  })
  it("has no legacy unversioned auth URL literals or old native fallback in shipped source",()=>{
    for(const file of sourceFiles(root)){
      const source=readFileSync(file,"utf8")
      expect(source).not.toMatch(/['"`]\/api\/auth\/(?:oidc|native)(?:\/|['"`])/)
    }
  })
})
