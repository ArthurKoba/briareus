/**
 * Closed HTTP METHOD+PATH allowlist extracted from the ACCEPTED A5 unmounted
 * platform_api.py, platform_auth_api.py, platform_overview_api.py, resource_api.py, platform_state_api.py and platform_command_status.py declarations.
 * This is a private development surface, NOT a public API activation gate.
 */
import { DraftContractError, draftUuid } from "@/features/platform/api/draft/source-contract"

const UUID = "[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
const route = (source: string): RegExp => new RegExp(`^${source}$`, "i")
const TEAM = `/teams/${UUID}`
const PROJECT = `/projects/${UUID}`
const USER = `/users/${UUID}`
const SESSION = `${PROJECT}/sessions/${UUID}`
const RESOURCE = `/(?:integrations|variables)/${UUID}`
const RESOURCE_PROJECT = `${PROJECT}/(?:integrations|variables)`
const RESOURCE_TEAM = `${TEAM}/(?:integrations|variables)`
const OPERATION = "[A-Za-z][A-Za-z0-9_.:-]{0,127}"

export type SourceMethod = "GET" | "POST" | "PATCH" | "DELETE"
const methods: Record<SourceMethod, readonly RegExp[]> = {
  GET: [
    route("/(?:me|me/context|users|invitations|teams|projects|operator/summary|providers/catalog)"),
    route(`${TEAM}/(?:members|member-details|permissions)`),
    route(`${PROJECT}/(?:permissions|access|agents|sessions|approvals|grants-catalog|operational-state)`),
    route(`${PROJECT}/commands/${OPERATION}/status`),
    route(RESOURCE_PROJECT),
    route(`${RESOURCE_PROJECT}/resolve`),
    route(RESOURCE_TEAM),
  ],
  POST: [
    route("/(?:auth/login|auth/logout|auth/refresh|teams|projects|invitations|registration|password/change|password/reset|integrations|variables)"),
    route(`${TEAM}/(?:members|transfer-owner)`),
    route(`${PROJECT}/(?:transfer-owner|admin-reassign|agents|sessions)`),
    route(`${USER}/(?:suspend|restore|superuser|password-reset)`),
    route(`${SESSION}/(?:elevation|revoke)`),
    route(`${PROJECT}/approvals/${UUID}/resolve`),
    route(`${RESOURCE}/rotate`),
  ],
  PATCH: [route(`${PROJECT}/agents/${UUID}(?:/state)?`),route(RESOURCE)],
  DELETE: [
    route(`${TEAM}/members/${UUID}`),
    route(USER),
    route(`/invitations/${UUID}`),
    route(RESOURCE),
  ],
}
const commandStatus = route(`${PROJECT}/commands/${OPERATION}/status`)
const operationalState = route(`${PROJECT}/operational-state`)
const userList = route("/users")
const projectResource = route(RESOURCE_PROJECT)
const projectResolve = route(`${RESOURCE_PROJECT}/resolve`)

/** Throws before any network request for a path/method not declared in source. */
export function requireSourceRoute(method: SourceMethod, input: string): void {
  if (!input.startsWith("/") || input.startsWith("//") || /[\\\x00-\x1f\x7f]/.test(input) || input.length > 4096) {
    throw new DraftContractError("source_route_path_invalid")
  }
  const queryStart = input.indexOf("?")
  const pathname = queryStart === -1 ? input : input.slice(0, queryStart)
  const query = queryStart === -1 ? "" : input.slice(queryStart + 1)
  if (!methods[method].some(pattern => pattern.test(pathname))) {
    throw new DraftContractError("source_route_not_declared")
  }
  if (method !== "GET" && queryStart !== -1) throw new DraftContractError("mutation_query_not_declared")
  const values = new URLSearchParams(query)
  if (method === "GET" && projectResource.test(pathname)) {
    if ([...values.keys()].some(key => key !== "scope") || values.getAll("scope").length > 1) throw new DraftContractError("source_query_invalid")
    const scope = values.get("scope")
    if (scope !== null && !["all", "team", "project"].includes(scope)) throw new DraftContractError("source_scope_invalid")
  } else if (method === "GET" && projectResolve.test(pathname)) {
    if ([...values.keys()].some(key => !["scope", "resource_id", "name"].includes(key)) ||
        ["scope", "resource_id", "name"].some(key => values.getAll(key).length > 1)) {
      throw new DraftContractError("source_query_invalid")
    }
    const scope = values.get("scope")
    if (scope !== null && !["all", "team", "project"].includes(scope)) throw new DraftContractError("source_scope_invalid")
    const id = values.get("resource_id")
    const name = values.get("name")
    if (Boolean(id) === Boolean(name)) throw new DraftContractError("qualified_resource_required")
    if (id) draftUuid(id)
    if (name && (name.length < 1 || name.length > 128)) throw new DraftContractError("resource_name_invalid")
  } else if(method==="GET"&&userList.test(pathname)) {
    // A5 User directory: limit only, 1..250, no cursor/offset. It is NOT
    // possible to prove absence of an older User from a capped response.
    if(queryStart!==-1 && ([...values.keys()].some(key=>key!=="limit")||
        values.getAll("limit").length!==1||
        !/^(?:[1-9]|[1-9][0-9]|1[0-9]{2}|2[0-4][0-9]|250)$/.test(values.get("limit")??""))) {
      throw new DraftContractError("source_user_list_limit_invalid")
    }
  } else if(method==="GET"&&operationalState.test(pathname)) {
    if(queryStart!==-1){
      if([...values.keys()].some(key=>key!=="limit")||values.getAll("limit").length!==1||
          !/^(?:[1-9]|[1-9][0-9]|100)$/.test(values.get("limit")??"")) {
        throw new DraftContractError("operational_limit_invalid")
      }
    }
  } else if (method==="GET"&&commandStatus.test(pathname)) {
    if(queryStart!==-1)throw new DraftContractError("source_query_not_declared")
  } else if (queryStart !== -1) {
    throw new DraftContractError("source_query_not_declared")
  }
}
