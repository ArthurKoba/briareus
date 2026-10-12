#!/usr/bin/env python3
"""Read-only static verifier for D4 four-owner release candidate; no tests/network/DB.

A11 source is external and unaccepted while in Backend worktree. Use
--source-root to inspect that exact worktree, then repeat against accepted
orchestrator fan-in. Never promote staging-source PASS into Docker/DB_RUNTIME.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shlex
import tomllib
from pathlib import Path

import yaml
from watch_impact import REPO, ROOT, watch_list

OWNERS = {
    'identity': ('identity','briareus_identity','IDENTITY'),
    'authorization': ('access','briareus_access','ACCESS'),
    'platform': ('platform','briareus_platform','CONTROL'),
    'resources': ('resources','briareus_resources','CATALOG'),
}
MODULES = frozenset({
    'external','identity','authorization','platform','resources','admin-api','admin-ui',
    'gateway','files','terminal','web','svc','infrastructure','reverse',
})
REQUIRED = re.compile(r'\$\{([A-Z][A-Z0-9_]*):\?\}')
SHARED = re.compile(r'\{\{(team|project|environment)\.([A-Z][A-Z0-9_]*)\}\}')
NETWORK = {'briareus':{'external':True,'name':'briareus-net'}}


def fatal(reason: str) -> None:
    raise RuntimeError(reason)


def docker_copies(path: Path) -> list[str]:
    copies=[]
    for raw in path.read_text().splitlines():
        if not raw.lstrip().startswith('COPY '):
            continue
        args=shlex.split(raw.strip())[1:]
        if any(x.startswith('--from=') for x in args):
            continue
        copies.extend(x for x in args[:-1] if not x.startswith('--'))
    return copies


def watch_covered(source: str, watches: list[str]) -> bool:
    return source in watches or any(
        x.endswith('/**') and (source==x[:-3] or source.startswith(x[:-3]+'/'))
        for x in watches
    )


def check_independently_recomputed_source_graph(
    source_root: Path, units: dict[str, object]
) -> None:
    """Fail closed if changed Backend/Runtime imports outrun Docker COPY/Watch.

    Only call accepted pure source-graph functions. Do NOT stage/build wheels
    or install packages to reproduce release dependency coverage.
    """
    import sys

    source_root=source_root.resolve()
    if not (source_root/'scripts/owner_source_graph.py').is_file():
        fatal('accepted Backend exact source-graph producer absent')
    if not (source_root/'services/bridge/package_graph.py').is_file():
        fatal('accepted Runtime exact source-graph producer absent')
    sys.path.insert(0,str(source_root/'scripts'))
    sys.path.insert(0,str(source_root/'services/bridge'))
    from owner_source_graph import source_closure
    from package_graph import release_manifest
    backend=source_closure(source_root)
    runtime=release_manifest(source_root)
    owners={'identity':'identity','authorization':'access',
            'platform':'platform','resources':'resources'}
    for module, record in units.items():
        if module in owners:
            owner=owners[module]
            expected={file['path'] for package in ('common',owner)
                      for file in backend['units'][package]}
        elif module in runtime['release_units']:
            item=runtime['release_units'][module]
            if item['dynamic_imports_to_review']:
                fatal(f'{module}: runtime source graph has unresolved dynamic imports')
            expected=set(item['source_paths'])
        elif module=='admin-api':
            # Private C2 remains injection-gated; nevertheless its precise
            # transitive Python imports MUST be packaged into this image.
            from admin_api_source_graph import private_admin_files
            expected=set(private_admin_files(source_root))
        else:
            fatal(f'{module}: no reviewed source-graph owner')
        actual=set(record['files'])
        if actual!=expected:
            fatal(f'{module}: real source graph no longer matches copied inputs: '
                  f'missing={sorted(expected-actual)} surplus={sorted(actual-expected)}')
    print('ACCEPTED_OWNER_RUNTIME_SOURCE_GRAPH_12_OF_12_EXACT')


def run(source_root: Path, allow_pending: bool) -> None:
    registry=json.loads((ROOT/'APPLICATIONS.json').read_text())
    apps=registry['applications']
    if {a['module'] for a in apps} != MODULES or len(apps)!=len(MODULES):
        fatal('exact 14 module registry is required')
    if len({a['name'] for a in apps})!=len(apps):
        fatal('duplicate Application display name')
    if {p.name for p in ROOT.iterdir() if p.is_dir() and p.name not in {'__pycache__', '.ruff_cache'}} != MODULES-{'external'}:
        fatal('wrong deploy module directories')
    if registry['provisioning_status']!='source_only_uv_direct_live_provisioning_blocked':
        fatal('live Apply guard not present')
    if registry.get('management',{}).get('build_strategy')!='coolify_uv_frozen_per_service_source_run_no_first_party_wheels':
        fatal('uv direct build source of truth is missing')
    docs=sorted(p.name for p in ROOT.glob('*.md'))
    if docs != ['README.md']:
        fatal(f'duplicate active deployment manuals: {docs}')
    if (ROOT/'FANIN.json').exists():
        fatal('obsolete provider-parent FANIN must not be active')
    source_inputs=json.loads((ROOT/'SELECTIVE_UV_SOURCE.json').read_text())
    source_units=source_inputs['modules']
    expected_python=MODULES-{'external','admin-ui'}
    if set(source_units)!=expected_python:
        fatal('source-only uv graph must cover exactly twelve Python Apps')
    check_independently_recomputed_source_graph(source_root,source_units)
    cfg=registry['configuration_contract']
    manifest=json.loads((source_root/'services/external/config/owner-databases.json').read_text())
    rows={x['module']:x for x in manifest['initial']}
    if set(rows)!=set(OWNERS)|{'external'} or manifest['provisioning_status']!='automatic_on_data_start_pending_live_observation':
        fatal('five databases including Rauthy must be reconciled at External startup')
    if manifest.get('role_model') != 'shared_existing_postgres_principal_five_logical_databases':
        fatal('DB role configuration must use one accepted existing PostgreSQL principal')
    if manifest['legacy_database_do_not_migrate']!='briareus_dev':
        fatal('live historical DB may not be repurposed')
    if any(not value for key,value in manifest['immutable_guards'].items()
           if key!='no_live_creation_approved'):
        fatal('one or more existing DB/source safety invariants disabled')
    for module in MODULES:
        a=next(x for x in apps if x['module']==module)
        name=next(iter(a['compose_services']),None)
        if not name or len(a['compose_services'])!=(3 if module=='external' else 1):
            fatal(f'{module}: wrong declared service count')
        if module!='external' and name!=f'briareus-{module}':
            fatal(f'{module}: environment leaks into service naming')
        if a['base_directory']!=('/services/external' if module=='external' else f'/deploy/{module}') or a['docker_compose_location']!='/docker-compose.coolify.yaml':
            fatal(f'{module}: invalid source path')
        if a['watch_paths_source']!=('services/external/docker-compose.coolify.yaml#x-watch-path-coolify' if module=='external' else f'deploy/{module}/docker-compose.coolify.yaml#x-watch-path-coolify'):
            fatal(f'{module}: duplicate/mispointed Watch Paths registry')
        app_root=source_root/'services/external' if module=='external' else ROOT/module
        plain=app_root/'docker-compose.yaml'
        cool=app_root/'docker-compose.coolify.yaml'
        base=yaml.safe_load(plain.read_text())
        override=yaml.safe_load(cool.read_text())
        if base['networks']!=override['networks'] or base['networks']!=NETWORK:
            fatal(f'{module}: external network ownership mismatch')
        if base.get('volumes',{})!=override.get('volumes',{}):
            fatal(f'{module}: volume mapping changed between Compose files')
        if set(base['services'])!=set(a['compose_services']) or set(override['services'])!=set(a['compose_services']):
            fatal(f'{module}: registry/Compose services differ')
        # Exactly one public Coolify domain is generated: Gateway port 8000.
        # Saved legacy domains require separate live parser/router cutover.
        generated = [
            key for compose in (base, override)
            for service_def in compose['services'].values()
            for key in service_def.get('environment', {})
            if key.startswith(('SERVICE_URL_', 'SERVICE_FQDN_'))
        ]
        if module == 'gateway':
            magic_key = 'SERVICE_URL_BRIAREUS_GATEWAY_8000'
            gateway_env = override['services']['briareus-gateway']['environment']
            if generated != [magic_key] or gateway_env.get(magic_key) != '/':
                fatal('gateway: sole public generated route must target Gateway 8000')
            exposed = base['services']['briareus-gateway'].get('expose', [])
            if '8000' not in [str(port) for port in exposed]:
                fatal('gateway: public proxy port does not match exposed 8000')
        elif generated:
            fatal(f'{module}: public domain generation forbidden outside Gateway')
        for compose in (base, override):
            for service_def in compose['services'].values():
                env = service_def.get('environment', {})
                if any(k in env for k in ('PUBLIC_API_URL', 'PUBLIC_UI_URL')):
                    fatal(f'{module}: obsolete per-service public URL input')
                if any('${SERVICE_URL_' in str(v) or '${SERVICE_FQDN_' in str(v)
                       for v in env.values()):
                    fatal(f'{module}: parser-managed domain interpolated into Compose')
        # Telemetry configuration is never named SERVICE_*, which Coolify
        # reserves for generated values. Match real OpenTelemetry resource keys
        # through our Briareus-specific environment aliases.
        if module not in {'external','admin-ui'}:
            service = f'briareus-{module}'
            env = override['services'][service]['environment']
            if env.get('OTEL_SERVICE_NAMESPACE') != '${OTEL_SERVICE_NAMESPACE:?}':
                fatal(f'{module}: missing required Project OTEL service namespace')
            if env.get('OTEL_DEPLOYMENT_ENVIRONMENT_NAME') != '${OTEL_DEPLOYMENT_ENVIRONMENT_NAME:?}':
                fatal(f'{module}: missing required Environment OTEL deployment name')
            if env.get('OTEL_SERVICE_NAME') != '${OTEL_SERVICE_NAME:?}':
                fatal(f'{module}: OTEL_SERVICE_NAME must be an operator-required runtime input')
            shared = a['shared_variables']
            if shared.get('OTEL_SERVICE_NAMESPACE') != '{{project.OTEL_SERVICE_NAMESPACE}}':
                fatal(f'{module}: wrong Project telemetry namespace reference')
            if shared.get('OTEL_DEPLOYMENT_ENVIRONMENT_NAME') != '{{environment.OTEL_DEPLOYMENT_ENVIRONMENT_NAME}}':
                fatal(f'{module}: wrong Environment telemetry deployment reference')
        for service_env in (base['services'].values(), override['services'].values()):
            for entry in service_env:
                if any(key in entry.get('environment',{}) for key in ('SERVICE_NAMESPACE','DEPLOYMENT_ENVIRONMENT')):
                    fatal(f'{module}: legacy telemetry ENV detected')
        watches=watch_list(module)
        for path in watches:
            if path in {'deploy/README.md','deploy/SHA256SUMS','deploy/APPLICATIONS.json','deploy/watch_impact.py'} or path.startswith('docs/'):
                fatal(f'{module}: source-doc change triggers redeploy')
        if not watch_covered(('services/external/' if module=='external' else f'deploy/{module}/')+'docker-compose.yaml',watches) or not watch_covered(('services/external/' if module=='external' else f'deploy/{module}/')+'docker-compose.coolify.yaml',watches):
            fatal(f'{module}: Compose watch missing')
        for service,body in base['services'].items():
            if 'ports' in body or body.get('network_mode') == 'host':
                fatal(f'{module}: public host-port exposed')
            if body['networks']['briareus']['aliases']!=[service]:
                fatal(f'{module}: network alias mismatch')
            ext=override['services'][service]['extends']
            if ext!={'file':'docker-compose.yaml','service':service}:
                fatal(f'{module}: bad Coolify extends')
            for key,value in body.get('environment',{}).items():
                actual=override['services'][service]['environment'].get(key)
                if actual!=value and not (module=='external' and service=='briareus-rauthy' and key not in override['services'][service]['environment']):
                    fatal(f'{module}: base/Coolify ENV mismatch {key}')
            used=set(REQUIRED.findall(str(override['services'][service]['environment'])))
            bindings=a.get('shared_variables',{})
            allowed_required=set(bindings) | ({'OTEL_SERVICE_NAME'} if module not in {'external','admin-ui'} else set())
            if module=='external':
                allowed_required.add('RAUTHY_TRUSTED_PROXIES')
            if not used<=allowed_required:
                fatal(f'{module}: required ENV lacks scoped reference: {used-allowed_required}')
            for key,ref in bindings.items():
                match=SHARED.fullmatch(ref)
                if (match is None or match.group(2)!=key
                        or key not in cfg[match.group(1)+'_shared']):
                    fatal(f'{module}: bad Shared binding {key}')
        if module=='external':
            if (app_root/'greenfield_schema.py').exists():
                fatal('manual metadata initializer is forbidden')
            expected_data={
                'services/external/**',
            }
            if set(watches)!=expected_data:
                fatal('data: bootstrap inputs not fully watched')
            docker=(app_root/'Dockerfile')
            shell=(app_root/'postgres-entrypoint.sh')
            sql=(app_root/'owner-bootstrap.psql')
            if not all(p.is_file() for p in (docker,shell,sql)):
                fatal('data: missing existing-PostgreSQL-container owner bootstrap source')
            # This release uses only the existing PostgreSQL user/password.
            # Eight former owner-scoped credentials are not real inputs.
            data_env=override['services']['briareus-postgres']['environment']
            for prefix in ('IDENTITY','ACCESS','CONTROL','CATALOG'):
                for suffix in ('USER','PASSWORD'):
                    if f'{prefix}_POSTGRES_{suffix}' in data_env:
                        fatal('data: obsolete per-domain credentials still required')
            if 'CREATE ROLE ' in sql.read_text().upper():
                fatal('data: separate SQL role creation reintroduced')
            if sql.read_text().count('CREATE DATABASE')!=1 or '\\gexec' not in sql.read_text():
                fatal('data: automatic PostgreSQL database provisioning missing')
            if 'FROM postgres:18.6-alpine' not in docker.read_text():
                fatal('data: upstream PostgreSQL version changed')
            copy_ignore=(app_root/'Dockerfile.dockerignore').read_text()
            if any(x not in copy_ignore for x in ('!services/external/owner-bootstrap.psql',
                                                   '!services/external/postgres-entrypoint.sh')):
                fatal('data: Dockerfile context silently excludes bootstrap source')
            if 'ENTRYPOINT ["/usr/local/bin/briareus-postgres-entrypoint"]' not in docker.read_text():
                fatal('data: ordinary PostgreSQL entrypoint bootstrap gate missing')
            if base['services']['briareus-postgres']['build'] != {
                'context':'../..','dockerfile':'services/external/Dockerfile'
            }:
                fatal('data: PostgreSQL must build only its existing extended image')
            if base['services']['briareus-postgres']['healthcheck']['test'] != [
                'CMD-SHELL','pg_isready -U "$$POSTGRES_USER" -d postgres'
            ]:
                fatal('data: physical PostgreSQL health must not depend on optional domain provisioning')
            if 'stop_server\n            exit 1' in shell.read_text().split('if ! psql',1)[1].split('fi',1)[0]:
                fatal('data: optional owner bootstrap failure must not stop PostgreSQL')
            if 'wait "$child"' not in shell.read_text().split('if ! psql',1)[1].split('fi',1)[0]:
                fatal('data: blocked owner bootstrap must preserve underlying DB process')
            if 'docker-entrypoint.sh "$@" &' not in shell.read_text() or 'ON_ERROR_STOP=1' not in shell.read_text():
                fatal('data: SQL bootstrap not owned by existing PostgreSQL lifecycle')
            for db in ('briareus_identity','briareus_access','briareus_platform','briareus_resources','briareus_rauthy'):
                if db not in sql.read_text():
                    fatal(f'data: missing provisioned domain database: {db}')
            if a['dockerfile'] != 'services/external/Dockerfile':
                fatal('external: registry Dockerfile is not migrated')
            rauthy = base['services']['briareus-rauthy']
            if 'briareus_rauthy' != rauthy['environment']['PG_DB_NAME']:
                fatal('external: Rauthy must own its independent database')
            if 'ports' in rauthy or not rauthy['image'].startswith('ghcr.io/sebadob/rauthy@sha256:'):
                fatal('external: Rauthy must use private pinned upstream image')
            if set(base['volumes']) != {'postgres-data','valkey-data','rauthy-data'}:
                fatal('external: vendor state volumes differ from intended topology')
            continue
        docker=ROOT/module/'Dockerfile'
        if not docker.is_file() or a['dockerfile']!=f'deploy/{module}/Dockerfile':
            fatal(f'{module}: missing source Dockerfile')
        if f'deploy/{module}/Dockerfile' not in watches:
            fatal(f'{module}: Dockerfile changes not watched')
        if module!='admin-ui':
            if (ROOT/module/'wheel-pin.json').exists() or a.get('wheel_pin_source'):
                fatal(f'{module}: deprecated external wheel pin still active')
            if a.get('activation')!='source_only_uv_direct_image_build_live_activation_blocked':
                fatal(f'{module}: live activation guard removed')
            dockertext=docker.read_text()
            for forbidden in ('deploy/wheel_artifacts/', 'install_wheel_release.py',
                              'PYTHONPATH=', 'SERVICE_VERSION='):
                if forbidden in dockertext:
                    fatal(f'{module}: obsolete wheel distribution/runtime shortcut: {forbidden}')
            expected_deps='uv sync --frozen --no-dev --no-install-project'
            if f'RUN --mount=type=cache,target=/root/.cache/uv,sharing=shared {expected_deps}' not in dockertext:
                fatal(f'{module}: native per-service dependency-only uv sync missing')
            if 'uv build' in dockertext or 'uv pip install' in dockertext:
                fatal(f'{module}: first-party wheel pipeline is forbidden')
            if '"uv", "run", "--frozen", "--no-sync", "--no-dev"' not in dockertext:
                fatal(f'{module}: own service must run directly via uv run --no-sync')
            unit=source_units[module]
            sources=unit['files']
            if not sources or not isinstance(sources,dict):
                fatal(f'{module}: missing exact source input graph')
            dep=unit['dependency_project']
            expected_docker_sources=set(sources)|{
                dep['source'],dep['lock'],dep['python'],unit['provenance_script']
            }
            actual_docker_sources=set(docker_copies(docker))
            if actual_docker_sources!=expected_docker_sources:
                fatal(f'{module}: actual COPY differs from exact uv unit inputs')
            expected={f'deploy/{module}/Dockerfile',f'deploy/{module}/Dockerfile.dockerignore',
                      f'deploy/{module}/docker-compose.yaml',f'deploy/{module}/docker-compose.coolify.yaml',
                      *expected_docker_sources}
            if set(watches)!=expected or set(watches)!=set(unit['watches']):
                fatal(f'{module}: native Watch Paths differ from exact Docker/source inputs')
            if any(x in watches for x in ('services/**','scripts/**','pyproject.toml','uv.lock')):
                fatal(f'{module}: monolithic source or dependency watcher returned')
            ignore=(ROOT/module/'Dockerfile.dockerignore').read_text()
            if f'!deploy/{module}/' not in ignore or f'!deploy/{module}/uv-project/' not in ignore:
                fatal(f'{module}: uv-project or its parent hidden from Docker context')
            for src in expected_docker_sources:
                path=(ROOT/src.removeprefix('deploy/')) if src.startswith('deploy/') else source_root/src
                if not path.is_file() or f'!{src}' not in ignore:
                    fatal(f'{module}: source COPY input missing or Docker-ignored {src}')
            for src,target in sources.items():
                if f'COPY {src} /app/src/{target}' not in dockertext:
                    fatal(f'{module}: selected source mounted at wrong Python import path {src}')
            dep_project=tomllib.loads((ROOT/dep['source'].removeprefix('deploy/')).read_text())
            if dep_project.get('tool',{}).get('uv',{}).get('package') is not False:
                fatal(f'{module}: uv project must never install a first-party wheel')
            if not dep_project['project']['dependencies']:
                fatal(f'{module}: empty dependency resolution inputs')
            lock=tomllib.loads((ROOT/dep['lock'].removeprefix('deploy/')).read_text())
            if not any(x['name']==dep_project['project']['name'] for x in lock.get('package',[])):
                fatal(f'{module}: own uv lock is not aligned to its project')
            expected_pins={
                f"{pkg['name']}=={pkg['version']}" for pkg in lock.get('package',[])
                if pkg['name']!=dep_project['project']['name']
            }
            declared_pins=set(dep_project['tool']['uv'].get('constraint-dependencies',[]))
            if declared_pins!=expected_pins:
                fatal(f'{module}: unnecessary or missing transitive uv constraints')
            accepted_packages={
                pkg['name']:pkg['version']
                for pkg in tomllib.loads((source_root/'uv.lock').read_text())['package']
            }
            if any(accepted_packages.get(pkg['name'])!=pkg['version']
                   for pkg in lock.get('package',[])
                   if pkg['name']!=dep_project['project']['name']):
                fatal(f'{module}: dependency resolution diverged from accepted root lock')
            digest=hashlib.sha256(json.dumps(
                sorted((target,hashlib.sha256((source_root/src).read_bytes()).hexdigest())
                       for src,target in sources.items()),
                separators=(',',':')
            ).encode()).hexdigest()
            expected_version=f"0.1.0+{module.replace('-', '')}.s{digest[:12]}"
            if unit['version']!=expected_version:
                fatal(f'{module}: source digest differs from source-only release version')
            if unit.get('provenance_script')!='deploy/runtime_write_provenance.py':
                fatal(f'{module}: source-digest provenance generator absent')
            if f'RUN python /app/runtime_write_provenance.py {module}' not in dockertext:
                fatal(f'{module}: runtime release provenance not derived from image source bytes')
            writer=(ROOT/'runtime_write_provenance.py').read_text()
            if 'BRIAREUS_UV_SOURCE_VERSION' not in writer or 'write_source_metadata' not in writer:
                fatal(f'{module}: build-time version witness source missing')
            if unit['actual_first_party_install'] is not False:
                fatal(f'{module}: first-party source install re-enabled')

        else:
            for src in docker_copies(docker):
                path=ROOT/src.removeprefix('deploy/') if src.startswith('deploy/') else source_root/src
                if not path.exists() or not watch_covered(src,watches):
                    fatal(f'{module}: UI COPY input missing/unwatched {src}')
        if module in OWNERS:
            # A failed DB/Alembic/trust prerequisite must stop the owner
            # process and stay stopped, not spin in an endless restart loop.
            if base['services'][f'briareus-{module}'].get('restart') != 'no':
                fatal(f'{module}: failed owner startup must not auto-restart')
            expected_apps={'identity':'identity.platform_runtime:app',
                           'authorization':'authorization.platform_runtime:app',
                           'platform':'projects.control_runtime:app',
                           'resources':'projects.catalog_runtime:app'}
            if f'"{expected_apps[module]}"' not in docker.read_text():
                fatal(f'{module}: owner startup does not use the Backend A11 entrypoint')
            if (ROOT/module/'asgi.py').exists():
                fatal(f'{module}: redundant duplicated private owner ASGI entrypoint')
            owner, db, env_key=OWNERS[module]
            record=rows[module]
            if (record['owner'],record['database'],record['role_env'],record['secret_env'])!=(owner,db,'POSTGRES_USER','POSTGRES_PASSWORD'):
                fatal(f'{module}: DB owner manifest mismatch')
            env=override['services'][f'briareus-{module}']['environment']
            if env.get('OTEL_SERVICE_NAME')!='${OTEL_SERVICE_NAME:?}':
                fatal(f'{module}: OTel service_name mismatches real owner_runtime telemetry identity')
            if env['POSTGRES_DB']!=db or env['POSTGRES_HOST']!='briareus-postgres':
                fatal(f'{module}: stale / shared god database target')
            if env['POSTGRES_USER']!='${POSTGRES_USER:?}' or env['POSTGRES_PASSWORD']!='${POSTGRES_PASSWORD:?}':
                fatal(f'{module}: owner App must use canonical POSTGRES_USER/PASSWORD inputs')
            if any(k.startswith('MIGRATION_POSTGRES_') for k in env):
                fatal(f'{module}: second DB migration credential contract returned')
            for app_key in ('POSTGRES_USER','POSTGRES_PASSWORD'):
                ref='{{environment.'+app_key+'}}'
                if a['shared_variables'].get(app_key)!=ref:
                    fatal(f'{module}: existing PostgreSQL credential binding missing: {app_key}')
            if any(k.startswith('MIGRATION_POSTGRES_') for k in a['shared_variables']):
                fatal(f'{module}: legacy migration Shared variables returned')
            if any(k.startswith('owner_role') for k in record):
                fatal(f'{module}: redundant separate PostgreSQL principal returned')
            if (source_root/'services/common/owner_migration_roles.py').exists():
                fatal('obsolete separate migrator module returned')
            runtime_source=(source_root/'services/common/owner_runtime.py').read_text()
            if 'await migrate_owner(database, local, phase_change=diagnostic_phase)' not in runtime_source:
                fatal('normal owner startup no longer runs own Alembic revisions')
            if 'result = await verify_owner(database, local)' not in runtime_source:
                fatal('independent read-only verification after migration missing')
            if 'alembic_greenfield' in docker.read_text()+cool.read_text():
                fatal(f'{module}: old global Alembic graph in deploy image')
            # Domain owner migrations ship inside the local uv-installed Hatch package.
            # Shared services/scripts input is intentionally watched until a reviewed split.
            if 'alembic_greenfield' in docker.read_text()+cool.read_text():
                fatal(f'{module}: old global Alembic graph remains reachable')
        elif module=='admin-api':
            env=override['services']['briareus-admin-api']['environment']
            if any(key.startswith('POSTGRES_') for key in env) or 'POSTGRES_USER' in a.get('shared_variables',{}):
                fatal('Admin API cannot retain direct shared database owner settings')
        elif module=='admin-ui':
            if 'OTLP_BEARER_TOKEN' in str(override):
                fatal('browser receives collector secret')
    external=yaml.safe_load((source_root/'services/external/docker-compose.coolify.yaml').read_text())
    if set(external['volumes'])!={'postgres-data','valkey-data','rauthy-data'}:
        fatal('External Compose must own exactly three concise named volumes')
    if any(value != {} for value in external['volumes'].values()):
        fatal('External Compose must use Coolify-scoped volumes with no custom physical name')
    rauthy=external['services']['briareus-rauthy']
    if any(x.get('target') == '/app/config.toml' for x in rauthy.get('volumes',[]) if isinstance(x,dict)):
        fatal('External Rauthy must configure via native ENV, never missing config bind')
    if (source_root/'services/external/rauthy/config.toml').exists():
        fatal('unused Rauthy TOML should not remain as a second config source')
    if 'allow-owner' in (ROOT/'authorization/docker-compose.yaml').read_text():
        fatal('unapproved Auth runtime bypass')
    if any(ROOT.glob('*/wheel-pin.json')) or (ROOT/'install_wheel_release.py').exists():
        fatal('old external wheel release artifacts still active')
    print('UV_DIRECT_SOURCE_STATIC_PASS; 14 Apps, 28 YAML, 12 first-party uv images, four owner DBs')
    print('Frozen per-service uv-dependencies; exact source COPY; uv run --no-sync; zero first-party wheel artifacts.')
    print('Actual Coolify image BUILD, new SQL role/DB/OS/C2 acceptance not established by STATIC.')


def main() -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, default=REPO)
    parser.add_argument('--allow-pending-owner-source',action='store_true')
    a=parser.parse_args()
    run(a.source_root,a.allow_pending_owner_source)
    return 0


if __name__=='__main__':
    try: raise SystemExit(main())
    except (ValueError,KeyError,AssertionError,RuntimeError,OSError) as exc:
        print(f'STATIC_REJECTED: {exc}')
        raise SystemExit(1) from None
