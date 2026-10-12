# Private Hand capability and readiness contract (v1)

**Owner:** Runtime, `shared/hand_runtime` and `hands/{files,terminal,web,svc,reverse,infrastructure}`.
This contract supports internal discovery of the source-port state without implying
that a caller may execute any tool. It replaces guessing enabled capabilities
from green Coolify liveness or the Control Panel's source-only module catalog.

## Internal private HTTP endpoints

- `GET /health/live` — HTTP 200 if the **process** is alive, regardless of
  whether MCP, its callers or tools are usable. Existing Coolify liveness uses
  this and must not be interpreted as readiness.
- `GET /health/ready` — HTTP 503, with `state: not_ready` while the Hand is a
  health-only ASGI process and the verified identity/AgentSession/Cedar
  admission layer is absent. There is no grace permit or privileged shortcut.
- `GET /internal/v1/capabilities` — HTTP 200, JSON, private network only, no
  tokens, secret state, user IDs or enabled operations. The JSON shape is:

```json
{
  "schema_version": 1,
  "hand": "files",
  "source": "packaged_tool_declarations",
  "declared_tool_count": 12,
  "interface_format": "python_declaration_not_mcp_json_schema",
  "declared_tools": [
    {
      "name": "file_read",
      "module": "modules.files.file_tools",
      "title": "File read",
      "arguments": [
        {"name": "path", "annotation": "str", "required": true},
        {"name": "offset", "annotation": "int", "required": false, "default": 0},
        {"name": "length", "annotation": "int", "required": false}
      ],
      "return_annotation": "JsonObject",
      "source_annotation_ref": "read_annotations"
    }
  ],
  "mcp_transport": "not_mounted",
  "authorization": "not_configured",
  "execution": "disabled"
}
```

The example `declared_tools` array is shortened for documentation; an actual
response includes all parsed declarations. The *count* is the number of
source-level `@mcp.tool(...)` function declarations found in the source tree,
not a claim that a tool is mounted, registered with any consumer or safe to
invoke. Names, static titles, docstrings, return annotations, parameter type
expressions, literal primitive defaults and any source annotation reference
are derived by Python AST without constructing tools or instantiating clients.

**This is a source-signature format, not MCP `tools/list` or a validated input
JSON Schema.** Complex types such as `ClientFile`, `JsonObject`, unions and
Pydantic models are retained as literal annotation expressions, *not* silently
converted into incorrect or permissive JSON schemas. Dynamic default values
are omitted; such parameters may have `required: false` without a `default`
field. Source annotation names such as `read_annotations` are only identifiers,
not current permission grants, verified read-only guarantees or executable
capability flags. A real FastMCP registration and per-effect authorization are
still needed before invoking a tool. The copied implementation lives inside
the Hand, never imported from `services/` at runtime.

Every response is non-cacheable. Other paths, including `/mcp` and private
provider operations, remain HTTP 503 and WebSockets remain rejected until
real Rauthy access token signature/issuer/audience and fresh Cedar/AgentSession
checks are implemented at the effect boundary. No public domain is added.

## Integration boundary

The **Control Panel UI must not access Hand container URLs directly**. The
Backend owner may eventually expose a narrowly authorized BFF catalog using
this nonsecret internal schema, after it has reviewed the real current owner
contract. No fake active tool status or synthetic capabilities are permitted.
The UI's modules (e.g. GitHub/GitLab under SVC and analysis under Reverse) are
presentation groups, not one-to-one deployment resources. Business operations
remain under existing owner scopes. `shared/hand_runtime` has one Runtime owner;
other independently deployed modules may consume only its explicitly scoped
`shared/hand_runtime/**` Watch input.
