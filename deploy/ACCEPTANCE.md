# Briareus D3-ENV deployment-source handoff

Status: **READY_FOR_REVIEW candidate — SOURCE/STATIC only. No live variable migration or deployment performed.**

## Unified A8/B12/R10 deployment alignment

- Data uses only `POSTGRES_PASSWORD` and `VALKEY_PASSWORD` as required operator secrets; `POSTGRES_USER=briareus`, `POSTGRES_DB=briareus_dev`, `TZ=UTC` are safe defaults.
- No `PLATFORM_*` or `PLATFORM_DEV_*` appears in staged Compose/Dockerfiles.
- Admin API current A8 ASGI default is health-only, so D does not pre-provision database/JWT/credential/UI URL settings into that Application.
- Authorization remains fail-closed and receives no future signing/database secrets until its accepted signed composition is activated.
- Admin UI packaging removes obsolete runtime-config ENV, template/entrypoint COPYs and Watch Paths. Its staged runtime ENV is only `TZ`.
- Gateway/Files/Terminal/Web/Reverse pseudo-ENV requested by R10 are removed; their guarded exit-78 activation boundary remains unchanged.
- Project Shared is the only secret scope. Bootstrap maps only **currently required** secret variables to `{{project.KEY}}` and never reads Shared secret values.
- Staged `deploy/data/greenfield_schema.py` is byte-identical to hardened A7 source with global user-relation emptiness guard, advisory transaction lock and `_dev` database guard.

## Evidence

`verify_deploy_static.py` must prove: 11 module directories, 22 Compose files, 11 Dockerfiles, external `briareus-net`, no host ports, Compose/Coolify env parity, COPY→Watch coverage, no pseudo/legacy ENV names, exactly two current required operator secrets, and hardened schema equality.

Python source compilation and full package SHA256 verification are required at handoff. This evidence does not establish image BUILD, Coolify parser behavior, DEV_RUNTIME or C1-B2/C2 protected runtime acceptance.
