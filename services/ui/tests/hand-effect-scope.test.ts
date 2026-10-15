import {describe,expect,it} from "bun:test"
import {
  parseHandEffectScope,parseHandEffectScopes,hasCompleteHandScopeCoverage,
} from "../src/shared/lib/hand-effect-scope"

const files={hand:"files",tool:"read_file",action:"files.read",
  resource:{kind:"workspace_path",id:"docs/source.txt"}}
describe("exact Runtime/Authorization Hand resource scope mapping",()=>{
  it("accepts the pinned six Hand effect/resource pair vocabularies",()=>{
    for(const [hand,tool,action,kind] of [
      ["files","read_file","files.read","workspace_path"],
      ["terminal","exec","terminal.execute","workspace"],
      ["web","navigate","web.access","origin"],
      ["svc","repository_status","integrations.use","repository"],
      ["reverse","import","analysis.import","analysis_project"],
      ["infrastructure","deploy_status","variables.use","application"],
    ] as const){
      expect(parseHandEffectScope({hand,tool,action,resource:{kind,id:"resource-01"}},[action])?.hand).toBe(hand)
    }
  })
  it("rejects Gateway-only or reserved action/Hand impersonation",()=>{
    for(const action of [
      "project.metadata.read","agents.manage","integrations.manage",
      "variables.manage","terminal.execute","web.access",
    ])expect(parseHandEffectScope({...files,action},[action])).toBeNull()
    expect(parseHandEffectScope({...files,action:"files.write"},["files.write"])?.action).toBe("files.write")
    expect(parseHandEffectScope({...files,hand:"web"},["files.read"])).toBeNull()
    expect(parseHandEffectScope({...files,resource:{kind:"origin",id:"origin-01"}},["files.read"])).toBeNull()
  })
  it("rejects prototype property names instead of throwing on inherited entries",()=>{
    for(const hand of ["constructor","__proto__","toString","hasOwnProperty"]){
      expect(parseHandEffectScope({...files,hand},["files.read"])).toBeNull()
      expect(parseHandEffectScopes([{...files,hand}],["files.read"])).toBeNull()
    }
  })
  it("requires the exact canonical selector shape, NFC and tool grammar",()=>{
    for(const modified of [
      {...files,extra:"grant"},
      {...files,tool:"../../shell"},
      {...files,tool:"9bad"},
      {...files,resource:{kind:"workspace_path",id:" docs/a "}},
      {...files,resource:{kind:"workspace_path",id:"dir\nchild"}},
      {...files,resource:{kind:"workspace_path",id:"e\u0301"}},
      {...files,resource:{kind:"workspace_path",id:"src/file",extra:"x"}},
      {...files,resource:{kind:"Workspace_Path",id:"foo"}},
    ])expect(parseHandEffectScope(modified,["files.read"])).toBeNull()
  })
  it("rejects duplicates or an unrepresented elevated action",()=>{
    expect(parseHandEffectScopes([files,files],["files.read"])).toBeNull()
    const parsed=parseHandEffectScopes([files],["files.read"])!
    expect(hasCompleteHandScopeCoverage(["files.read"],parsed)).toBe(true)
    expect(hasCompleteHandScopeCoverage(["files.read","files.write"],parsed)).toBe(false)
    expect(hasCompleteHandScopeCoverage(["project.metadata.read"],[])).toBe(false)
  })
  it("rejects resource scopes not included in server operations",()=>{
    expect(parseHandEffectScopes([files],["terminal.execute"])).toBeNull()
    expect(parseHandEffectScopes(new Array(33).fill(files),["files.read"])).toBeNull()
  })
})

describe("owner-returned compact Files Project selectors",()=>{
  const project='11111111-1111-4111-8111-111111111111'
  const other='22222222-2222-4222-8222-222222222222'
  const id='project-path-v1:'+project+':'+('a'.repeat(64))
  const scope={...files,resource:{kind:'workspace_path',id}}
  it("accepts the committed namespace only for its Files Project",()=>{
    expect(parseHandEffectScope(scope,['files.read'],project)?.resource.id).toBe(id)
    expect(parseHandEffectScope(scope,['files.read'],other)).toBeNull()
    expect(parseHandEffectScopes([scope],['files.read'],other)).toBeNull()
    expect(parseHandEffectScope({...scope,hand:'web',action:'web.access',resource:{kind:'origin',id}},['web.access'],project)).toBeNull()
  })
  it("rejects reserved version aliases, malformed UUIDs and noncanonical fingerprints",()=>{
    for(const bad of [id.replace('v1','v2'),id.replace('4111','1111'),id.toUpperCase().replace('PROJECT-PATH-','project-path-'),id.slice(0,-1),id+':extra','project-path-raw:README.md']){
      expect(parseHandEffectScope({...scope,resource:{kind:'workspace_path',id:bad}},['files.read'],project)).toBeNull()
    }
    // Nonreserved resources stay governed by their existing owner contract.
    expect(parseHandEffectScope(files,['files.read'],project)?.resource.id).toBe('docs/source.txt')
  })
})
