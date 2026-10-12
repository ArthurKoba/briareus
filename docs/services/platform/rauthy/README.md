# Rauthy — upstream identity service for Briareus Development

**2026-10-12 status: SOURCE ONLY; no Coolify deployment, IdP URL, JWKS, or user session verified.**
Source owner: Deployment. The existing Identity service and its data stay running
until a later explicitly accepted cutover.

## Upstream evidence

Official project: https://github.com/sebadob/rauthy
Version: v0.37.1 (security update, 7 October 2026).
Release: https://github.com/sebadob/rauthy/releases/tag/v0.37.1
Official Docker: https://sebadob.github.io/rauthy/getting_started/docker.html
Reference config: https://github.com/sebadob/rauthy/blob/v0.37.1/config.toml
Verified against GHCR public OCI manifest 2026-10-12: multiarch index
SHA256 72b4734a7c52bd67cd544e7b72a4ab64932a7060844ef475fc2bb3d3da3074d9;
contains Linux amd64 and arm64. Deployment pins this exact digest, NOT latest.

Rauthy provides User/Service OAuth2/OIDC, password/MFA, sessions and signing
keys. Briareus Authorization retains Cedar, grants and AgentSessions. Team
and Project ownership remains in Briareus Platform Control. No Rauthy source
fork, homemade issuer/JWT/password implementation or wheel artifacts here.

## Independent service inputs

- services/platform/rauthy/config.toml — nonsecret Rauthy server/database settings.
- services/platform/rauthy/docker-compose.yaml — immutable upstream image,
  scoped required secrets, rootless container, separate persistent storage.
- services/platform/rauthy/docker-compose.coolify.yaml — 3 narrow Watch Paths
  and the single upstream service declaration.
- This file is the nonsecret provider/operator contract.

Internal HTTP port: 8080; NO direct published port or additional public
domain. Existing Briareus approved origin is https://briareus.koba-nexus.ru.
The Gateway's correct, future reverse-proxy route and exact trusted-proxy
source CIDR are Runtime-owned and NOT YET VERIFIED. The named volume
briareus-dev-rauthy-v1 persists /app/data independently of old PostgreSQL
and Valkey. Rauthy docs require persistent Hiqlite cache/Raft state even when
the primary database backend is PostgreSQL. Upstream process runs as uid 10001.

## PostgreSQL, namespace, and schema migrations

Official Rauthy accepts HIQLITE=false plus PG_HOST, PG_PORT, PG_DB_NAME,
PG_USER, PG_PASSWORD and performs its own schema initialization/migrations.
Proposed isolated logical DB: briareus_rauthy on the ONE current
briareus-postgres server. **This DB is NOT CREATED OR AUTHORIZED YET.**
It cannot use the existing briareus_identity, briareus_access,
briareus_platform, briareus_resources or briareus_dev databases.
It is never permissible to DROP, replace, migrate-from, auto-stamp or
silently create a new SQL server/role/database. The source references
the existing approved scoped POSTGRES_USER and POSTGRES_PASSWORD variable
NAMES only. Actual values remain protected in the future Application.

No MIGRATE_DB_FROM or existing Briareus Alembic is used.
Rauthy alone will own schema revisions inside its separately authorized DB.
A new DB + volume approval and actual database authorization are separate
pre-deployment checks, not proof of runtime from this Compose.

## Scoped runtime variable names (never actual secret values)

Existing, required Environment Shared: POSTGRES_USER, POSTGRES_PASSWORD.
New Rauthy-specific protected secret variables, required:
RAUTHY_HQL_SECRET_RAFT, RAUTHY_HQL_SECRET_API, RAUTHY_ENC_KEYS,
RAUTHY_ENC_KEY_ACTIVE, RAUTHY_BOOTSTRAP_ADMIN_PASSWORD_ARGON2ID.
Required nonsecret target variables:
RAUTHY_TRUSTED_PROXIES, RAUTHY_BOOTSTRAP_ADMIN_EMAIL.

In the container the official names are HQL_SECRET_RAFT, HQL_SECRET_API,
ENC_KEYS, ENC_KEY_ACTIVE, TRUSTED_PROXIES, BOOTSTRAP_ADMIN_PASSWORD_ARGON2ID,
BOOTSTRAP_ADMIN_EMAIL. Both HQL authentication secrets must be distinct and
stable even if PostgreSQL is the primary DB; ENC_KEYS and ENC_KEY_ACTIVE
must stay stable across restarts and be rotated only via upstream procedure.
TRUSTED_PROXIES must be the confirmed source CIDR of the private gateway,
never an unrestricted CIDR or a trust-all forwarded-header configuration.
No secret material, default password, local test config, client token or
private API key must appear in Git, container image metadata, browser or chat.
Sensitive Coolify variables are Runtime only, not Docker build inputs.
Required Compose interpolation prevents deployment with missing references.

The static candidate config uses:
- Postgres DB briareus_rauthy and one-node persistent Hiqlite cache.
- PUB_URL briareus.koba-nexus.ru, RP_ID briareus.koba-nexus.ru.
- RP_ORIGIN https://briareus.koba-nexus.ru:443.
- LISTEN_SCHEME http; PROXY_MODE true, with REQUIRED trusted CIDR.
- LOCAL_TEST false, public Swagger disabled.
All public/OIDC URL semantics still require verification from live discovery
through the final Runtime Gateway route before any client/redirect is enabled.

## Operator bootstrap and Admin API

Upstream first start creates admin@localhost and shows an auto-generated
initial password ONCE in logs when no secure password was provided. It does
NOT implement the historical Briareus first-superuser invitation link.
For operator-controlled bootstrap this manifest instead REQUIRES an upstream
supported precomputed Argon2id admin password hash and operator E-mail.
No plaintext default, expired/reusable invitation or homemade OAuth grant.

Upstream Admin UI: /auth/v1/admin; protected Admin REST supports scoped
API Keys through Authorization: API-Key NAME$SECRET. Provision a narrow
credential with only required Users/Groups/Clients rights after authorized
enrollment; the key must never reach the Panel browser. Do not invent
concrete REST request paths before Rauthy's own authenticated API docs
are validated. Sources:
https://sebadob.github.io/rauthy/config/bootstrap.html
https://sebadob.github.io/rauthy/work/api_keys.html
https://sebadob.github.io/rauthy/getting_started/first_start.html

## OIDC issuer and consumer handoff — NOT LIVE

Rauthy v0.35+ changed the issuer to have a trailing slash:
candidate https://briareus.koba-nexus.ru/auth/v1/
Candidate discovery:
https://briareus.koba-nexus.ru/auth/v1/.well-known/openid-configuration

Before sending a VERIFIED contract, query the actual scoped running provider
and check issuer, authorization_endpoint, token_endpoint, jwks_uri,
end_session_endpoint, supported scopes/resources and exact client audience
from the OIDC discovery JSON. A nonsecret client_id, allowed redirect URI
and callback path will be defined jointly with Backend/Runtime/Frontend,
never guessed. Panel receives BFF-only credentials, Gateway stays a proxy,
Hands separately check token audiences and Authorization/Cedar decisions.

## Verified upstream route declarations (v0.37.1 source, NOT live)

Official tagged Rust source: https://github.com/sebadob/rauthy/blob/v0.37.1/src/api/src/oidc.rs
Routes are mounted under the Rauthy /auth/v1 API prefix.

- GET /auth/v1/oidc/authorize: OIDC interactive authorization.
- POST /auth/v1/oidc/token: token exchange and refresh.
- GET /auth/v1/oidc/certs: signing keys.
- GET and POST /auth/v1/oidc/logout: logout variants.
- GET /auth/v1/.well-known/openid-configuration: OIDC discovery.
- GET /auth/v1/.well-known/oauth-authorization-server: extra metadata.

Official Admin REST relative route declarations: src/api/src/users.rs,
clients.rs, groups.rs, roles.rs and api_keys.rs; these handle /users,
/clients, /groups, /roles, /api_keys. They are upstream PROTECTED REST
routes, not Briareus browser BFF endpoints.

Static upstream source does NOT prove a live issuer, JWKS URI, client
audience, callback, authorization grants or final reverse-proxy path.
Backend/Runtime/Frontend must consume actual returned discovery JSON after
new Coolify target authorization and first supported provider enrollment.

## Hard Coolify authorization boundary

Project Briareus MCP UUID 3xshlpoghb9wcyhjgktlqzzp;
Development environment UUID naibrku1omovvmw5o0bcnp5c.
Only 14 existing UUIDs in docs/operations/BRIAREUS_DEV_ACCESS_SCOPE.md
are currently allowlisted. There is no approved Rauthy Application UUID.
Do NOT create/browse/edit a new Rauthy App until the EXACT target allowlist
has been amended; do NOT repurpose the old Identity Application to evade
this restriction. No access to other environments, projects, shared/global
Coolify screens, or secret values. Keep the existing PostgreSQL, Volumes,
Gateway and Identity unchanged.

Next, the Orchestrator must authorize an exact new coexisting Rauthy
Development Application target and isolated briareus_rauthy DB provisioning.
Then Deployment can provision the source-only service, validate actual Rauthy
CLI config, Docker image health, upstream schema, issuer/discovery/JWKS,
operator enrollment and narrowly scoped Admin API. Only a SUCCESSFUL
live provider observation permits handoff to other three agent lanes.

Validation level: current SOURCE/STATIC + official GHCR digest. NOT a real
Docker image build, Rauthy config runtime validation, OAuth login, or Dev deploy.
