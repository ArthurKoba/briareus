# Authorization → Gateway / Hands: private Cedar decision API

**Status: source API staged, not live Rauthy authorization.** The independent `services/authorization` runtime mounts `POST /internal/v1/authorization/decide` but ships with `decision_service=None`. It therefore **always responds 503**, rather than allowing a user, agent or service to self-assert an identity or permission. It has no public Gateway route or Coolify-generated FQDN. The control-panel API/UI is absent from the execution path.

### Private request

```json
{
  "project_uuid": "<UUIDv4>",
  "agent_session_uuid": "<UUIDv4>",
  "action": "mcp.connect",
  "expected_grant_revision": 1
}
```

`action="mcp.connect"` is **Gateway-only coarse session admission**, checking that the caller has a real active session with nonempty operations and that Cedar admits the connection. It is **not** permission for any tool execution. For a Hand, `action` must instead be the exact already approved scope (e.g. `files.read`, `terminal.execute`), and the Hand must perform its additional resource/argument-specific authorization before each side effect. Unsupported actions deny. Stored active grant, actor/project/session match, exact current revision, expiry, and elevation are evaluated from Authorization's own PostgreSQL `briareus_access` under a transaction, with the Rust-backed Cedar policy embedded via `cedarpy`.

**Response semantics:** HTTP 200 `{"allowed":true}` only after all verified evidence and a current Cedar Permit; 401 when a configured verifier rejects caller authentication, 403 for a real Deny or verified scope mismatch, 503 for absent trusted identity/session peer adapter or authoritative data. Request bodies cannot specify trusted User IDs, proof issuers or verified peer attributes. No unsigned `X-Actor-Id`/`X-User-Id` or flat internal network may substitute for authentication. Other 4xx are boundary format errors. No bearer, grant or reason leakage in success.

### Actual activation requirements

The Backend/Deployment/Runtime handoff must supply an independently reviewed implementation of `TrustedDecisionAttestor`: real Rauthy access-token issuer/JWKS/signature/expiry/audience validation, service-peer authentication for the Gateway or particular Hand, canonical stable subject → internal User link, **fresh** Platform Project/member/active status, and a bounded expiry. A trusted factory must also inject `AuthorizationDecisionReader(PlatformDatabase(OwnerDatabaseSettings(owner="access")))` as the owner-local SQL authority. Never fabricate an issuer, client key or caller just to make this API return Allow. The deployed default remains unconfigured until those inputs exist; an API or UI outage must not become an Authorization dependency.

No automated suites are added in the MVP. Native import, compiled Cedar, fail-closed local ASGI requests and release image source-closure checks prove only source behavior. Real Dev acceptance requires a new, explicitly authorized Coolify Application UUID because the former Authorization UUID was deleted, then live peer/OAuth/Project attestation plus an actual allow → deny → revoke sequence at a protected Hand. See issue #490. Retain existing PostgreSQL data and the legacy compose as rollback until runtime acceptance.
