# Briareus flat-layout: one batch, one CI gate

The selected owner layout is the repository-root `services/`, `hands/` and
`shared/`. This release plan replaces incremental per-service path edits as the
**coordination unit**, but never turns the 13 candidate Coolify applications
into one Compose stack. Each application retains its existing UUID, current
service DNS, volume authority and isolated deployment lifecycle.

## Source of truth

`flat-batch-cutover.json` contains every approved Development application
UUID exactly once: 13 target modules and 1 explicitly held Legacy Identity app.
The target Base Directory and native Watch Paths are the exact Git/Compose
contract; the Compose location is `/docker-compose.coolify.yaml` for every
candidate. No global watch paths. When a new shared module is truly consumed,
update only those actual consumers in the same batch PR/CI revision.

`python3 scripts/verify_flat_batch.py --uv-locks --compose` validates the
**entire candidate batch**; the CI `docker` job runs it on every PR. One
`workflow_dispatch` of the existing `CI` workflow with `build_images=true`
also builds all 13 candidate images from the same commit, collecting failures rather
than stopping on the first one. Required `test` and `docker` check identities
remain unchanged. The build images are validation artifacts, not proof of
Coolify deployments or product acceptance. The source gate additionally
checks whether a statically imported local Vite configuration dependency is
listed in UI Dockerfile COPY and the restrictive Dockerfile.dockerignore;
a host-native Vite build alone can pass while the actual Docker build context
is missing that file. This early source check is **not** Vue typecheck or an
actual built-image acceptance; those remain the owning Frontend/CI job.

## Public native-login observation (read-only, no credentials)

After a compatible Backend + Runtime + Frontend Development publish, run
`python3 scripts/probe_dev_native_auth.py`. It performs **only pinned public
GET** requests on `https://briareus.koba-nexus.ru` with normal TLS, strict
non-redirecting transport, bounded JSON/HTML responses and no cookies,
password, bearer, CSRF, secrets, session-creation or user login. It requires
`/panel/` HTML, the actual `/api/v1/auth/capabilities` Rauthy-native-v1 DTO,
the obsolete `/api/auth/native/capabilities` path closed, exact issuer
discovery, and private provider Admin REST denied by Gateway. It reports a
failed check for the current deployed old UI/API state; a `200` hosted Rauthy
page or a live Gateway says NOTHING about human login readiness. Even all
flags green do not prove the native password/MFA form, Project identity,
AgentSession/Cedar grant or protected Files action: those require separate
actual signed browser/owner/MCP acceptance in the same public Dev.

## Actual Development settings are a separate acceptance gate

The source manifest records **desired** Compose, Base Directory and module +
`services/external/**` Watch Paths. Coolify stores each Git application's
*currently saved* configuration separately; a reviewed Git merge does not
replace that runtime state. The read-only optional
`scripts/verify_flat_batch.py --coolify-snapshot <local-metadata-file>`
argument compares the bounded snapshot of all 14 **exact allowlisted UUIDs**
with the manifest, verifies a fresh (at most one-hour-old) collection, and
reports missing/duplicate/extra saved Watch Paths, incorrect Git repository,
branch, Base Directory and Compose path. It does **not** contact Coolify,
reveal variables, read secrets, or change any Application. The normal source
and CI gate runs without a snapshot; passing it says nothing about saved Dev
settings. The optional snapshot format contains only scope, capture time,
nonsecret Application fields, and explicit per-UUID lookup failures. A 404
or timeout is **unverified** rather than evidence that an Application was
deleted; never recreate it to satisfy a failed check.

Before the one coordinated cutover, use the exact approved UUID read-only
Application surface to collect this evidence, do not query global Coolify
inventories/Shared/other projects. Resolve missing apps and the saved Watch
Path discrepancy under each owning release actor and preserve any current
known-good state; do not blindly overwrite configuration because Git looks
correct. `running:healthy` or `running:unknown` is metadata, never evidence
that users can authenticate or a Files AgentSession may execute. Any missing
approved UUID, unapproved ENV key, unsigned resource grant or unreviewed
intermediate deployment blocks live activation, even if source CI passes.

## Previously deployed owner schema compatibility — required before owner cutover

A source-green Compose/uv-lock check cannot establish the schema head in an
**already populated** Dev owner database. The prior actual Coolify Application
may have applied a later Alembic revision than the candidate image ships.
For the **affected** Platform/Resources/Authorization owner, obtain the last
finished, exact 40-character SHA from the approved Application's scoped
Coolify deployment history, then run:

```bash
python3 scripts/verify_flat_batch.py --target platform \
  --previous-deployed-owner platform=<exact-previous-deployment-SHA>
```

The optional source gate parses both pinned, reviewed owner revision graphs
and their effective Dockerfile COPY histories, without reading database
credentials or changing any schema. It fails on removal of a previously
reviewed revision, rewriting an already shipped migration, truncating the
forward history or failing to read the previous packaged image source. For
Resources use `--target resources` and `resources=<SHA>`; Authorization uses
`--target authorization` and `authorization=<SHA>` (registry owner `access`).
`SOURCE_COMPATIBLE` is **not** a database or data-migration acceptance:
confirm the *actual* deployed owner database's `public.alembic_version` under
its own scoped, read-only SQL role, compare the installed schema and preserve
a recovery point before any additive change. If old packaged source cannot
be reconstructed, the tool reports **UNVERIFIED**, not "safe". Never use
`alembic stamp`, a reset, baseline rewrite or drop/recreate to force a PASS.

Concrete 15 October 2026 incident: Platform's last pre-preview deployed
source shipped `platform_0001→0002→0003`, while the new image rewrote `0001`
and retained only that head. Real SigNoz Dev errors for both Platform and
Resources say `phase=alembic_upgrade category=migration_state_unverified
exception=OwnerSchemaRejected`, so the affected services are not healthy
until Backend supplies a source-reviewed additive migration or a separately
scoped approved data recovery route. The exact persisted `alembic_version`
values have not been read, and the source-only check must not invent them.

## Startup and restart contract — staged, not globally atomic

The first MVP is one host but **not one Compose project**. Existing External
Services is ONE Coolify Application containing PostgreSQL, Valkey and Rauthy.
Its PostgreSQL health is scoped to the Rauthy **database prerequisite**;
success of the four-domain-DB reconciliation is independently recorded and
is not required for the provider to start after an unrelated owner failure.
The remaining Core, Gateway and Hands Applications retain their own UUID,
Compose, Watch Path and restart lifecycle. Docker Compose `depends_on` works
only for services inside the **same** Compose application; it cannot name a
service in another Coolify app, order global restarts or make a batch Git
merge atomic. Existing External Compose already gates Rauthy on its Postgres
owner-DB existence/health marker; Valkey has its own health check. Keep those
source-verified prerequisites rather than making every Core/Hand dependent
on a newly invented always-on privileged container. PostgreSQL's vendor health
uses a read-only **current Rauthy DB owner catalog check**, not only a startup
marker: a missing/foreign-owned provider DB must block later dependency starts
without blocking PostgreSQL service restart or independent owner migrations.

**Operational phases** (per release and on cold install; normal restart reuses
only its own phase as needed):

1. **Infrastructure preflight:** inside existing External Services, bring up
   existing Postgres/Valkey durable services. Reconcile *existence* and owner
   of the four logical DBs idempotently, preserving the Rauthy provider and
   all existing PGDATA/Valkey/Hiqlite volumes. This is not the place to run
   Access/Platform/Resources Alembic or reseed an existing user.
2. **Provider readiness:** Rauthy starts only with its supported owner DB and
   secret references; its upstream first-install migration creates the first
   admin *inside Rauthy's own initialization* only for a genuinely empty
   provider. The pinned upstream v0.37.1 first-init path is **not fully
   atomic**: once JWKs exist, a failure later in first bootstrap is not
   automatically replayed on restart. Do not reset the DB, parse first-login
   credentials out of logs, or run a fresh setup on a populated provider.
   A protected operator may choose a source-supported one-time Argon2id-hash
   bootstrap credential on a genuinely new install, subject to a separately
   approved Coolify variable contract; this is not an MVP dependency.
3. **Independent Core owners:** Authorization, Platform and Resources each
   performs its own reviewed, advisory-locked owner migration and strict
   schema/current identity/readiness check. The BFF/UI may expose liveness
   independently, but cannot grant protected operations until its real
   provider/User/Project/owner dependencies are functional. Failure of one
   owner does not trigger global bootstrap or reset another owner's DB.
4. **Execution activation:** Gateway and Hands may *start before* Core, but
   their protected MCP routes/effects must fail closed pending current
   issuer/JWKS, genuine resource token, Platform scope, Authorization/Cedar,
   private channel and Files root lease. An already-running Hand should
   converge when dependencies recover, without a forced all-container restart.
5. **Release orchestration:** run the existing large PR/CI/build contract,
   verify exact approved Development UUIDs and saved Coolify Watch Paths,
   then coordinate dependency-aware *sequential* app deployments/redeploys
   and consumer-side readiness. Preserve compatible intermediate states,
   original volumes, previous Git refs, held Identity and a reversible path.
   The release barrier is an *operator/orchestrator check*, not a persistent
   privileged process or permission to inspect new global secrets.

**One-shot bootstrap container?** Optional *within the existing External
Services Compose only* after separate verification of Coolify's parser,
service-completed dependency semantics, volume identity, environment
contract and rerun/recovery behavior. It must not become a new app/host
service or a universal owner-schema migrator. A one-time completed task is
not a durable barrier for subsequent independent restarts or continuous
Core readiness. No such container is being deployed by this plan.

**Lifecycle acceptance (different failure states, not interchangeable):**

- Fresh cluster: owner DB existence only, Rauthy first-init, own Core migrations,
  then protected endpoint acceptance. The current owner DB bootstrap has
  provider-first ordering to survive interruption between CREATE DATABASE
  operations; no provider state is overwritten on repeat startup.
- Repeat restart / single Core owner restart: no re-enrollment, no cross-owner
  schema migration and no requirement to restart already healthy neighbors.
- Provider/Core outage: unrelated processes may stay alive, but user/Files
  actions deny; do not interpret liveness as functional readiness.
- Partial first-install Rauthy bootstrap: report unsupported/unknown provider
  state for operator recovery, never reconstruct an IdP from empty credentials.
- Staged upgrade/rollback: verify exact source revision and the live consumer
  between phases; never pretend a 14-app update is atomic or downgrade an
  independently advanced schema without reviewed compatibility.

Source and isolated native PostgreSQL/Valkey tests establish only their own
contracts. Coolify-stored Watch Paths, real admin enrollment, inter-app DNS,
physical Dev owner schemas, provider token and genuine Files Permit require
separate exact-UUID runtime acceptance. Do not add new operator ENV or
shared-secret references from this architectural decision alone.

## Operational cutover gate

No bulk cutover until the whole candidate set has a green CI image pass, its
actual existing Dev resource has been compared against Git and captured for
rollback, and the owner-specific runtime prerequisites are demonstrably ready.
Especially for `services/external`, preserve PostgreSQL/Valkey volumes,
confirm supported Rauthy storage and non-secret config references, and do not
create another IdP application. Keep old Identity until actual OIDC/user
migration is verified. No agent inspects global projects, secrets or unapproved
UUIDs. Avoid forcing unavailable identity clients or Cedar permits to `allow`.

Batch saving a Base/Compose/Watch change does **not** deploy it; a follow-up
snapshot and exact Git revision/build/log read are required. A source-only
health-only Hand is not a working MCP provider: until a real verified token,
audience, policy and AgentSession grant are wired, all effects remain 503.
Retain old `deploy/<name>` / `services/hands/...` source and existing named
volumes for rollback. If any needed target is absent or any prerequisite is
unmet, report one batch-wide BLOCKED result rather than silently changing a
subset and calling it complete.

## Explicit legacy holds

- **Identity**: preserve the transitional application until real Rauthy
  sign-in, resource-token claims, user cutover and rollback are proven.
- **Platform Control and Resource Catalog**: the approved root
  `services/platform/` and `services/resources/` deployment definitions are
  not in published Git; Backend owns these migration decisions. No guessed
  paths or redeploys for them.

The separate ownership lanes retain their exclusive application source;
this batched gate coordinates evidence and timing, not source-edit rights.
