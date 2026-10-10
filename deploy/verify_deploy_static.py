#!/usr/bin/env python3
"""Static consistency check for Briareus module-first deployment source.

This is source/config verification only; it never runs Docker, Coolify, tests or network actions.
"""
from __future__ import annotations

import ast
import json
import re
import shlex
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent if (ROOT.parent / "services").is_dir() else ROOT.parents[3] / "repo"
MODULES = ("data","authorization","gateway","admin-api","admin-ui","files","terminal","web","svc","infrastructure","reverse")
NETWORK = {"briareus": {"external": True, "name": "briareus-net"}}
REQUIRED_ENV = re.compile(r"\$\{([A-Z][A-Z0-9_]*)\:\?\}")


def watch_list(path: Path) -> list[str]:
    obj = yaml.safe_load(path.read_text())
    value = obj.get("x-watch-path-coolify")
    assert isinstance(value, list) and value and len(value) == len(set(value)), path
    assert all(isinstance(x, str) and x and not x.startswith("/") and ".." not in x.split("/") for x in value), path
    return value


def copied_sources(dockerfile: Path) -> list[str]:
    result=[]
    for raw in dockerfile.read_text().splitlines():
        line=raw.strip()
        if not line.startswith("COPY "):
            continue
        tokens=shlex.split(line)
        if any(x.startswith("--from=") for x in tokens[1:]):
            continue
        sources=[x for x in tokens[1:-1] if not x.startswith("--")]
        result.extend(sources)
    return result


def covered(source: str, watches: list[str]) -> bool:
    if source in watches:
        return True
    source=source.rstrip("/")
    if source + "/**" in watches:
        return True
    for pattern in watches:
        if pattern.endswith("/**"):
            prefix=pattern[:-3].rstrip("/")
            if source == prefix or source.startswith(prefix + "/"):
                return True
    return False


def main() -> int:
    actual=tuple(sorted(p.name for p in ROOT.iterdir() if p.is_dir()))
    assert actual == tuple(sorted(MODULES)), (actual, MODULES)
    assert not (ROOT / "coolify").exists()
    # Old provider-parent paths may appear only in migration history prose, never in live registry/scripts/Compose.
    live_sources=[ROOT/"APPLICATIONS.json",ROOT/"bootstrap_coolify.py",ROOT/"sync_watch_paths_coolify.py"]
    live_sources.extend(ROOT.glob("*/docker-compose*.yaml"))
    assert all("deploy/coolify" not in q.read_text(errors="ignore") for q in live_sources), "stale provider-parent path in live deployment source"
    registry=json.loads((ROOT/"APPLICATIONS.json").read_text())
    apps=registry["applications"]
    assert len(apps)==11 and len({x["name"] for x in apps})==11
    assert len({x["module"] for x in apps})==11
    expected_app_names={
        "data":"External Services", "authorization":"Authorization", "admin-api":"Admin API",
        "admin-ui":"Admin UI", "gateway":"Gateway", "files":"Files", "terminal":"Terminal",
        "web":"Web", "svc":"SVC", "infrastructure":"Infrastructure", "reverse":"Reverse",
    }
    assert {x["module"]:x["name"] for x in apps}==expected_app_names
    assert registry["repository"]=="ArthurKoba/briareus"
    active_naming_sources=[ROOT/"APPLICATIONS.json",ROOT/"bootstrap_coolify.py",ROOT/"sync_watch_paths_coolify.py"]
    active_naming_sources.extend(ROOT.glob("*/docker-compose*.yaml"))
    allowed_physical_storage={
        "name: briareus-dev-postgres-v1",
        "name: briareus-dev-valkey-v1",
    }
    stale=[]
    for q in active_naming_sources:
        for lineno,line in enumerate(q.read_text(errors="ignore").splitlines(),1):
            if "briareus-dev-" in line and line.strip() not in allowed_physical_storage:
                stale.append((str(q),lineno,line.strip()))
    assert not stale, ("environment leaked into runtime/service name",stale)
    config=registry.get("configuration_contract")
    assert isinstance(config,dict)
    assert config.get("read_secret_values") is False
    assert set(config.get("team_shared",[]))=={"TZ","OTLP_ENDPOINT","OTLP_BEARER_TOKEN"}
    assert set(config.get("environment_shared",[]))=={"SERVICE_NAMESPACE","DEPLOYMENT_ENVIRONMENT","POSTGRES_USER","POSTGRES_PASSWORD","VALKEY_PASSWORD"}
    assert set(config.get("secret_keys",[]))=={"OTLP_BEARER_TOKEN","POSTGRES_PASSWORD","VALKEY_PASSWORD"}
    assert "project_shared_secrets_current" not in config
    for app in apps:
        bindings=app.get("shared_variables",{})
        for key,ref in bindings.items():
            assert ref in {f"{{{{team.{key}}}}}",f"{{{{environment.{key}}}}}"}
            assert key in set(config["team_shared"]+config["environment_shared"])
    live_sources.extend(ROOT.glob("*/Dockerfile"))
    live_text="\n".join(q.read_text(errors="ignore") for q in live_sources)
    forbidden_tokens=(
        "PLATFORM_", "PLATFORM_DEV_",
        "ADMIN_UI_PREVIEW", "ADMIN_UI_TELEMETRY", "ADMIN_UI_EVENTS_MODE",
        "ADMIN_API_BASE_URL", "OAUTH_ENABLED", "FILE_WORKSPACE_ROOT",
        "TERMINAL_WORKSPACE_ROOT", "TERMINAL_HOME", "BROWSER_PROFILE_PATH",
    )
    assert not any(token in live_text for token in forbidden_tokens), [t for t in forbidden_tokens if t in live_text]
    for module in MODULES:
        base=ROOT/module/"docker-compose.yaml"
        cool=ROOT/module/"docker-compose.coolify.yaml"
        docker=ROOT/module/"Dockerfile"
        assert base.is_file() and cool.is_file() and (module == 'data' or docker.is_file()), module
        a=yaml.safe_load(base.read_text()); b=yaml.safe_load(cool.read_text())
        assert a["networks"]==b["networks"]==NETWORK, module
        assert a.get("volumes",{})==b.get("volumes",{}), module
        assert set(a["services"])==set(b["services"]), module
        watches=watch_list(cool)
        forbidden_watch={"Dockerfile","docker-entrypoint.sh","deploy/README.md","deploy/ACCEPTANCE.md","deploy/SHA256SUMS","deploy/APPLICATIONS.json"}
        assert not (set(watches) & forbidden_watch), (module,"unrelated/shared deployment input watched")
        assert f"deploy/{module}/docker-compose.yaml" in watches
        assert f"deploy/{module}/docker-compose.coolify.yaml" in watches
        if module != "data":
            assert f"deploy/{module}/Dockerfile" in watches
        for service_name, service in a["services"].items():
            assert "ports" not in service, (module,service_name)
            assert service["networks"]["briareus"]["aliases"]==[service_name]
            ext=b["services"][service_name]["extends"]
            assert ext=={"file":"docker-compose.yaml","service":service_name}
            expected_env=dict(service["environment"])
            if module == "admin-ui":
                expected_env["SERVICE_URL_BRIAREUS_ADMIN_UI_8080"]="/"
            if module == "authorization":
                expected_env={
                    "TZ":"${TZ:-UTC}",
                    "OTLP_ENDPOINT":"${OTLP_ENDPOINT:-}",
                    "OTLP_BEARER_TOKEN":"${OTLP_BEARER_TOKEN:-}",
                    "SERVICE_NAMESPACE":"${SERVICE_NAMESPACE:-briareus}",
                    "DEPLOYMENT_ENVIRONMENT":"${DEPLOYMENT_ENVIRONMENT:-development}",
                    "OTEL_SERVICE_NAME":"authorization",
                    "POSTGRES_HOST":"briareus-postgres",
                    "POSTGRES_PORT":"5432",
                    "POSTGRES_DB":"briareus_dev",
                    "POSTGRES_USER":"${POSTGRES_USER:?}",
                    "POSTGRES_PASSWORD":"${POSTGRES_PASSWORD:?}",
                }
            if module == "admin-api":
                expected_env={
                    "TZ":"${TZ:-UTC}",
                    "OTLP_ENDPOINT":"${OTLP_ENDPOINT:-}",
                    "OTLP_BEARER_TOKEN":"${OTLP_BEARER_TOKEN:-}",
                    "SERVICE_NAMESPACE":"${SERVICE_NAMESPACE:-briareus}",
                    "DEPLOYMENT_ENVIRONMENT":"${DEPLOYMENT_ENVIRONMENT:-development}",
                    "OTEL_SERVICE_NAME":"admin-api",
                    "POSTGRES_HOST":"briareus-postgres",
                    "POSTGRES_PORT":"5432",
                    "POSTGRES_DB":"briareus_dev",
                    "POSTGRES_USER":"${POSTGRES_USER:?}",
                    "POSTGRES_PASSWORD":"${POSTGRES_PASSWORD:?}",
                    "SERVICE_URL_BRIAREUS_ADMIN_API_8000":"/",
                }
            assert b["services"][service_name]["environment"]==expected_env
            if module != "data":
                build=service["build"]
                assert build=={"context":"../..","dockerfile":f"deploy/{module}/Dockerfile"}, (module,build)
                virtual_base=REPO / "deploy" / module
                assert (virtual_base / build["context"]).resolve()==REPO.resolve(), (module,"wrong build context")
        if module != "data":
            for source in copied_sources(docker):
                actual=(ROOT.parent / source.removeprefix("deploy/")) if source.startswith("deploy/") else (REPO / source)
                assert actual.exists(), f"{module}: Docker COPY source missing: {source}"
                assert covered(source,watches), f"{module}: COPY input not watched: {source}"
        app=next(x for x in apps if x["module"]==module)
        assert app["base_directory"]==f"/deploy/{module}"
        assert app["docker_compose_location"]=="/docker-compose.coolify.yaml"
        assert app["watch_paths_source"]==f"deploy/{module}/docker-compose.coolify.yaml#x-watch-path-coolify"
        if module != "data":
            assert app["dockerfile"]==f"deploy/{module}/Dockerfile"
        else:
            assert "dockerfile" not in app and "schema_initializer" not in app
    # ENV-1: only Data currently consumes operator inputs; all other staged Apps are
    # fail-closed/health-only/static and must not receive future secrets preemptively.
    data=yaml.safe_load((ROOT/"data/docker-compose.yaml").read_text())
    data_pg=data["services"]["briareus-postgres"]["environment"]
    data_vk=data["services"]["briareus-valkey"]["environment"]
    assert data_pg=={
        "POSTGRES_DB":"${POSTGRES_DB:-briareus_dev}",
        "POSTGRES_USER":"${POSTGRES_USER:-briareus}",
        "POSTGRES_PASSWORD":"${POSTGRES_PASSWORD:?}",
        "TZ":"${TZ:-UTC}",
    }
    assert data_vk=={"VALKEY_PASSWORD":"${VALKEY_PASSWORD:?}","TZ":"${TZ:-UTC}"}
    for module in set(MODULES)-{"data","authorization"}:
        compose=yaml.safe_load((ROOT/module/"docker-compose.yaml").read_text())
        for service in compose["services"].values():
            assert service.get("environment",{})=={"TZ":"${TZ:-UTC}"}, (module,service.get("environment",{}))
    required=set()
    for q in ROOT.glob("*/docker-compose.coolify.yaml"):
        required.update(REQUIRED_ENV.findall(q.read_text()))
    assert required=={"POSTGRES_PASSWORD","POSTGRES_USER","VALKEY_PASSWORD"}
    assert required <= set().union(*(set(a.get("shared_variables",{})) for a in apps))
    assert set(data["services"])=={"briareus-postgres","briareus-valkey"}
    valkey=data["services"]["briareus-valkey"]["command"][0]
    assert subprocess.run(["sh","-n"],input=valkey,text=True,capture_output=True).returncode==0
    assert not (ROOT/"data/greenfield_schema.py").exists()
    assert not (ROOT/"data/Dockerfile").exists()
    authorization=(ROOT/"authorization/docker-compose.coolify.yaml").read_text()
    assert '"scripts/alembic_greenfield/**"' in authorization
    assert '"scripts/alembic.ini"' in authorization
    assert '"services/authorization/**"' in authorization
    assert '"uv.lock"' in authorization and '"pyproject.toml"' in authorization
    dockerfile=(ROOT/"authorization/Dockerfile").read_text()
    assert 'uv sync --frozen --no-dev --no-editable' in dockerfile
    assert 'authorization.platform_runtime:app' in dockerfile
    assert 'scripts/alembic_greenfield' in dockerfile
    assert '"--host", "0.0.0.0"' in dockerfile
    assert 'greenfield_schema.py' not in dockerfile
    assert 'metadata.create_all' not in dockerfile
    bootstrap=(ROOT/"bootstrap_coolify.py").read_text()
    ast.parse(bootstrap,filename="bootstrap_coolify.py")
    ast.parse((ROOT/"sync_watch_paths_coolify.py").read_text(),filename="sync_watch_paths_coolify.py")
    assert 'applications/{app_uuid}/start' not in bootstrap and '/restart' not in bootstrap and 'queue_application_deployment' not in bootstrap
    assert '"instant_deploy":False' in bootstrap and '"is_auto_deploy_enabled":False' in bootstrap
    assert '"autogenerate_domain":autogenerate_domain(root, spec)' in bootstrap
    assert 'bindings_by_app' in bootstrap and 'SHARED_REF.fullmatch(ref)' in bootstrap
    assert 'projects/{project_uuid}/envs' not in bootstrap
    assert 'projects/{project_uuid}/environments/{quote' not in bootstrap
    assert '"is_buildtime":False' in bootstrap
    assert '"is_runtime":True' in bootstrap
    assert '"--apply"' in bootstrap
    print("STATIC_PASS: 11 named Apps, 22 Compose, scoped Shared references, Auth packaged Alembic startup, required Postgres vars, retired Data manual initializer, C2 fail-closed")
    return 0

if __name__=="__main__":
    raise SystemExit(main())
