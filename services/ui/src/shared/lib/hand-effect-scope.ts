/** Typed local UI validation for owner-returned MCP Hand scopes.
 * Source authority: Backend Authorization _action_audiences.py and
 * _resource_scope.py; this helper does not authorize an action, allocate a
 * tool, mint a Cedar permit or validate current Resource Owner membership.
 *
 * Keep the resource/action map exact to Runtime's six real Hand PEPs.
 */
export const HAND_EFFECT_ACTIONS = {
  files: ["files.read", "files.write"],
  terminal: ["terminal.execute"],
  web: ["web.access"],
  svc: ["integrations.use", "variables.use"],
  reverse: ["analysis.import"],
  infrastructure: ["integrations.use", "variables.use"],
} as const
export const HAND_RESOURCE_KINDS = {
  files: ["workspace_path"],
  terminal: ["workspace", "job"],
  web: ["browser_session", "origin"],
  svc: ["repository"],
  reverse: ["analysis_project", "artifact"],
  infrastructure: ["application"],
} as const

export type HandEffectName=keyof typeof HAND_EFFECT_ACTIONS
export interface HandEffectScope {
  hand:HandEffectName
  tool:string
  action:string
  resource:{kind:string;id:string}
}
const TOOL=/^[A-Za-z][A-Za-z0-9_.-]{0,127}$/
const KIND=/^[a-z][a-z0-9_]{0,63}$/
const FILES_PROJECT_SELECTOR=/^project-path-v1:([0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}):[0-9a-f]{64}$/
/** Validate the reserved owner selector namespace; never generate selectors
 * from arbitrary browser paths or infer ownership from a matching digest. */
function matchesProjectNamespace(hand:string,kind:string,id:string,projectUuid?:string):boolean {
  if(!id.startsWith("project-path-"))return true
  const match=FILES_PROJECT_SELECTOR.exec(id)
  return hand==="files"&&kind==="workspace_path"&&!!match&&
    (projectUuid===undefined||match[1]===projectUuid)
}
function isRecord(value:unknown):value is Record<string,unknown>{
  return typeof value==="object"&&value!==null&&!Array.isArray(value)
}
function exactKeys(value:Record<string,unknown>,keys:readonly string[]):boolean{
  return Object.keys(value).length===keys.length&&
    keys.every(key=>Object.prototype.hasOwnProperty.call(value,key))
}
export function parseHandEffectScope(value:unknown,operations:readonly string[],projectUuid?:string):HandEffectScope|null {
  if(!isRecord(value)||!exactKeys(value,["hand","tool","action","resource"]))return null
  const resource=value.resource
  if(!isRecord(resource)||!exactKeys(resource,["kind","id"]))return null
  const hand=value.hand
  if(typeof hand!=="string"||!Object.prototype.hasOwnProperty.call(HAND_EFFECT_ACTIONS,hand))return null
  const name=hand as HandEffectName
  const allowedActions:readonly string[]=HAND_EFFECT_ACTIONS[name]
  const kinds:readonly string[]=HAND_RESOURCE_KINDS[name]
  if(typeof value.tool!=="string"||!TOOL.test(value.tool)||
    typeof value.action!=="string"||!allowedActions.includes(value.action)||
    !operations.includes(value.action)||
    typeof resource.kind!=="string"||!KIND.test(resource.kind)||
    !kinds.includes(resource.kind)||
    typeof resource.id!=="string"||resource.id.length<1||resource.id.length>512||
    resource.id!==resource.id.normalize("NFC")||
    resource.id!==resource.id.trim()||
    Array.from(resource.id).some(c=>c.codePointAt(0)!<32||c.codePointAt(0)===127)||
    !matchesProjectNamespace(name,resource.kind,resource.id,projectUuid))return null
  return {
    hand:name,
    tool:value.tool,
    action:value.action,
    resource:{kind:resource.kind,id:resource.id},
  }
}
/** Python owner normalizes on canonical 5-tuple and rejects duplicate grants. */
export function parseHandEffectScopes(
  values:unknown,
  operations:readonly string[],
  projectUuid?:string,
):HandEffectScope[]|null {
  if(!Array.isArray(values)||values.length>32)return null
  const parsed:HandEffectScope[]=[],unique=new Set<string>()
  for(const value of values){
    const item=parseHandEffectScope(value,operations,projectUuid)
    if(!item)return null
    const key=JSON.stringify([
      item.hand,item.tool,item.action,item.resource.kind,item.resource.id,
    ])
    if(unique.has(key))return null
    unique.add(key)
    parsed.push(item)
  }
  return parsed
}
/** Every requested elevated MCP effect needs at least one exact resource
 * scope. An approval with reserved Gateway-only actions is not representable.
 */
export function hasCompleteHandScopeCoverage(
  operations:readonly string[],
  scopes:readonly HandEffectScope[],
):boolean {
  return operations.length>0&&
    operations.every(action=>scopes.some(scope=>scope.action===action))&&
    scopes.every(scope=>operations.includes(scope.action))
}
