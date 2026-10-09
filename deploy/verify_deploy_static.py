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
    assert registry["repository"]=="ArthurKoba/briareus"
    config=registry.get("configuration_contract")
    assert isinstance(config,dict)
    assert config.get("secret_scope")=="project"
    assert config.get("secret_reference")=="{{project.KEY}}"
    assert config.get("forbidden_shared_scope")=="environment"
    assert config.get("read_secret_values") is False
    current_secrets=set(config.get("project_shared_secrets_current",[]))
    assert current_secrets=={"POSTGRES_PASSWORD","VALKEY_PASSWORD"}
    assert set(config.get("required_application_nonsecrets_current",[]))==set()
    assert "project_shared_secrets_future" not in config
    assert "required_application_nonsecrets_future" not in config
    assert "apply_blocked_pending_backend" not in config
    live_sources.extend(ROOT.glob("*/Dockerfile"))
    live_text="\n".join(q.read_text(errors="ignore") for q in live_sources)
    forbidden_tokens=(
        "PLATFORM_", "PLATFORM_DEV_", "{{environment.",
        "ADMIN_UI_PREVIEW", "ADMIN_UI_TELEMETRY", "ADMIN_UI_EVENTS_MODE",
        "ADMIN_API_BASE_URL", "OAUTH_ENABLED", "FILE_WORKSPACE_ROOT",
        "TERMINAL_WORKSPACE_ROOT", "TERMINAL_HOME", "BROWSER_PROFILE_PATH",
    )
    assert not any(token in live_text for token in forbidden_tokens), [t for t in forbidden_tokens if t in live_text]
    for module in MODULES:
        base=ROOT/module/"docker-compose.yaml"
        cool=ROOT/module/"docker-compose.coolify.yaml"
        docker=ROOT/module/"Dockerfile"
        assert base.is_file() and cool.is_file() and docker.is_file(), module
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
            assert b["services"][service_name]["environment"]==service["environment"]
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
        app=next(x for x in apps if x["name"]==f"briareus-dev-{module}")
        assert app["base_directory"]==f"/deploy/{module}"
        assert app["docker_compose_location"]=="/docker-compose.coolify.yaml"
        assert app["watch_paths_source"]==f"deploy/{module}/docker-compose.coolify.yaml#x-watch-path-coolify"
        assert app["dockerfile"]==f"deploy/{module}/Dockerfile"
    # ENV-1: only Data currently consumes operator inputs; all other staged Apps are
    # fail-closed/health-only/static and must not receive future secrets preemptively.
    data=yaml.safe_load((ROOT/"data/docker-compose.yaml").read_text())
    data_pg=data["services"]["briareus-dev-postgres"]["environment"]
    data_vk=data["services"]["briareus-dev-valkey"]["environment"]
    assert data_pg=={
        "POSTGRES_DB":"${POSTGRES_DB:-briareus_dev}",
        "POSTGRES_USER":"${POSTGRES_USER:-briareus}",
        "POSTGRES_PASSWORD":"${POSTGRES_PASSWORD:?}",
        "TZ":"${TZ:-UTC}",
    }
    assert data_vk=={"VALKEY_PASSWORD":"${VALKEY_PASSWORD:?}","TZ":"${TZ:-UTC}"}
    for module in set(MODULES)-{"data"}:
        compose=yaml.safe_load((ROOT/module/"docker-compose.yaml").read_text())
        for service in compose["services"].values():
            assert service.get("environment",{})=={"TZ":"${TZ:-UTC}"}, (module,service.get("environment",{}))
    required=set()
    for q in ROOT.glob("*/docker-compose.coolify.yaml"):
        required.update(REQUIRED_ENV.findall(q.read_text()))
    assert required=={"POSTGRES_PASSWORD","VALKEY_PASSWORD"}
    assert current_secrets==required
    assert set(data["services"])=={"briareus-dev-postgres","briareus-dev-valkey"}
    valkey=data["services"]["briareus-dev-valkey"]["command"][0]
    assert subprocess.run(["sh","-n"],input=valkey,text=True,capture_output=True).returncode==0
    schema=next(x for x in apps if x["name"]=="briareus-dev-data")["schema_initializer"]
    assert schema["dockerfile"]=="deploy/data/Dockerfile" and schema["script"]=="deploy/data/greenfield_schema.py"
    assert (ROOT/"data/greenfield_schema.py").read_text()==(REPO/"scripts/greenfield_schema.py").read_text()
    bootstrap=(ROOT/"bootstrap_coolify.py").read_text()
    ast.parse(bootstrap,filename="bootstrap_coolify.py")
    ast.parse((ROOT/"sync_watch_paths_coolify.py").read_text(),filename="sync_watch_paths_coolify.py")
    assert 'applications/{app_uuid}/start' not in bootstrap and '/restart' not in bootstrap and 'queue_application_deployment' not in bootstrap
    assert '"instant_deploy":False' in bootstrap and '"is_auto_deploy_enabled":False' in bootstrap
    assert '"{{project."+key+"}}"' in bootstrap
    assert 'projects/{project_uuid}/envs' not in bootstrap
    assert 'projects/{project_uuid}/environments/{quote' not in bootstrap
    assert '{{environment.' not in bootstrap
    print("STATIC_PASS: module-first deploy + ENV-1 contract, 11 Apps, 22 Compose, COPY→Watch, Project Shared secret policy, canonical Data-only operator inputs, no pseudo ENV, A8/B12/R10 packaging alignment, hardened schema source")
    return 0

if __name__=="__main__":
    raise SystemExit(main())
