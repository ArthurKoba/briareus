# Infrastructure Hand — private health-only independent service

Owned by Runtime, Briareus MCP/development only. This module has no host
admin privileges, credential readers or MCP effect tools. **Health is not
authenticated MCP availability.** All protected paths currently return 503.

The Rauthy issuer/JWKS/audience and Authorization Cedar AgentSession decision
interface are not yet supplied by their owners. Never mount privileged tools
before per-resource OAuth signature+audience validation and current signed
Authorization permit are verified, including failure/expiry/revocation.

Existing Dev Infrastructure application UUID:
`mfhydae1l2xkxxkf31gomrw2`. At native service-folder cutover, change
**only** that existing application's Base to
`/services/hands/infrastructure`, Compose to `/docker-compose.coolify.yaml`,
and native Watch to `services/hands/infrastructure/**`. Preserve existing
app UUID, internal DNS alias, Briareus Docker network, existing data and
secret references; do not create a public domain. Rollback to the recorded
legacy `/deploy/infrastructure` Compose/Watch and redeploy only this app.

Network segregation of **future untrusted executor processes** is a separate
required physical acceptance: this health-only front door starts no executor.
A process sharing `briareus-net` must NEVER be treated as an isolated sandbox.
Use a distinct network namespace without connectivity to private Identity,
Rauthy administration, PostgreSQL, Valkey or Control Panel before executing
untrusted tools; no protected tool may be enabled on the present shell.
