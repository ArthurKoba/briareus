from __future__ import annotations

import asyncio
import fcntl
import json
import os
import pty
import re
import shutil
import signal
import struct
import termios
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from common.models import JsonObject
from common.settings import TerminalSettings
from modules.files.file_store import FileStore

_WORKSPACE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class TerminalError(RuntimeError):
    """Base terminal/workspace error."""


@dataclass
class Job:
    job_id: str
    workspace_id: str
    command: str
    cwd: str
    interactive: bool
    label: str
    state: str
    created_at: float
    started_at: float
    ended_at: float | None
    exit_code: int | None
    signal_number: int | None
    pid: int | None
    log_path: Path
    metadata_path: Path
    log_truncated: bool = False
    process: asyncio.subprocess.Process | None = None
    master_fd: int | None = None
    reader_task: asyncio.Task[None] | None = None
    watcher_task: asyncio.Task[None] | None = None


def _timestamp(value: float | None) -> str | None:
    if value is None:
        return None
    return datetime.fromtimestamp(value, UTC).isoformat()


class TerminalManager:
    def __init__(self, settings: TerminalSettings, file_store: FileStore | None = None) -> None:
        self.settings = settings
        self.file_store = file_store
        self.workspace_root = settings.workspace_root
        self.projects_root = self.workspace_root / "projects"
        self.jobs_root = self.workspace_root / ".terminal" / "jobs"
        self.home = settings.home
        self._jobs: dict[str, Job] = {}
        self._prepare_storage()
        self._load_persisted_jobs()

    def _prepare_storage(self) -> None:
        self.projects_root.mkdir(parents=True, exist_ok=True)
        self.jobs_root.mkdir(parents=True, exist_ok=True)
        self.home.mkdir(parents=True, exist_ok=True)

    def _workspace_id(self, value: str) -> str:
        workspace_id = value.strip()
        if not _WORKSPACE_RE.fullmatch(workspace_id) or workspace_id in {".", ".."}:
            raise TerminalError(
                "workspace_id must start with an alphanumeric character and contain only "
                "letters, digits, dot, underscore or hyphen"
            )
        return workspace_id

    def workspace_path(self, workspace_id: str) -> Path:
        workspace_id = self._workspace_id(workspace_id)
        path = (self.projects_root / workspace_id).resolve(strict=False)
        if not path.is_relative_to(self.projects_root.resolve(strict=False)):
            raise TerminalError("workspace path escapes workspace root")
        return path

    def _require_workspace(self, workspace_id: str) -> Path:
        path = self.workspace_path(workspace_id)
        if not path.is_dir():
            raise TerminalError(f"workspace not found: {workspace_id}")
        return path

    def resolve_cwd(self, workspace_id: str, cwd: str = "") -> Path:
        base = self._require_workspace(workspace_id).resolve(strict=False)
        value = cwd.strip()
        candidate = base if not value else (base / value).resolve(strict=False)
        if not candidate.is_relative_to(base):
            raise TerminalError("cwd escapes workspace")
        if not candidate.is_dir():
            raise TerminalError(f"cwd is not a directory: {cwd}")
        return candidate

    def workspace_create(self, workspace_id: str) -> JsonObject:
        workspace_id = self._workspace_id(workspace_id)
        path = self.workspace_path(workspace_id)
        created = not path.exists()
        path.mkdir(parents=True, exist_ok=True)
        return {
            "workspace_id": workspace_id,
            "path": str(path),
            "created": created,
        }

    def workspace_list(self) -> JsonObject:
        items = []
        if self.projects_root.is_dir():
            for path in sorted(self.projects_root.iterdir(), key=lambda item: item.name.casefold()):
                if not path.is_dir():
                    continue
                stat = path.stat()
                items.append(
                    {
                        "workspace_id": path.name,
                        "path": str(path),
                        "modified_at": _timestamp(stat.st_mtime),
                        "active_jobs": sum(
                            1
                            for job in self._jobs.values()
                            if job.workspace_id == path.name
                            and job.state in {"running", "cancelling"}
                        ),
                    }
                )
        return {"workspaces": items, "count": len(items)}

    def workspace_info(self, workspace_id: str) -> JsonObject:
        path = self._require_workspace(workspace_id)
        stat = path.stat()
        usage = shutil.disk_usage(path)
        return {
            "workspace_id": workspace_id,
            "path": str(path),
            "modified_at": _timestamp(stat.st_mtime),
            "disk": {
                "total_bytes": usage.total,
                "used_bytes": usage.used,
                "free_bytes": usage.free,
            },
            "jobs": [
                self._job_public(job)
                for job in sorted(
                    self._jobs.values(),
                    key=lambda item: item.created_at,
                    reverse=True,
                )
                if job.workspace_id == workspace_id
            ],
        }

    async def workspace_delete(self, workspace_id: str, force: bool = False) -> JsonObject:
        workspace_id = self._workspace_id(workspace_id)
        path = self._require_workspace(workspace_id)
        active = [
            job
            for job in self._jobs.values()
            if job.workspace_id == workspace_id and job.state in {"running", "cancelling"}
        ]
        if active and not force:
            raise TerminalError(
                "workspace has active jobs: " + ", ".join(job.job_id for job in active)
            )
        if force:
            for job in active:
                await self.job_cancel(job.job_id, grace_seconds=1)
        shutil.rmtree(path)
        return {"workspace_id": workspace_id, "deleted": True}

    def _workspace_file_path(self, workspace_id: str, path: str) -> Path:
        base = self._require_workspace(workspace_id).resolve(strict=False)
        raw = path.strip()
        if not raw:
            raise TerminalError("path is required")
        candidate = (base / raw).resolve(strict=False)
        if not candidate.is_relative_to(base):
            raise TerminalError("path escapes workspace")
        return candidate

    def workspace_import_file(
        self,
        workspace_id: str,
        file_id: str,
        path: str,
        overwrite: bool = False,
    ) -> JsonObject:
        if self.file_store is None:
            raise TerminalError("Files integration is not configured")
        workspace_id = self._workspace_id(workspace_id)
        destination = self._workspace_file_path(workspace_id, path)
        if destination.exists() and not overwrite:
            raise TerminalError(f"destination already exists: {path}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        source = self.file_store.path_for(file_id)
        shutil.copyfile(source, destination)
        return {
            "workspace_id": workspace_id,
            "file_id": file_id,
            "path": str(destination),
            "size_bytes": destination.stat().st_size,
        }

    def workspace_export_file(
        self,
        workspace_id: str,
        path: str,
        name: str = "",
        mime_type: str = "",
    ) -> JsonObject:
        if self.file_store is None:
            raise TerminalError("Files integration is not configured")
        workspace_id = self._workspace_id(workspace_id)
        source = self._workspace_file_path(workspace_id, path)
        if not source.is_file():
            raise TerminalError(f"workspace file not found: {path}")
        result = self.file_store.put_file(
            source,
            name=name.strip() or source.name,
            mime_type=mime_type,
            source="terminal-workspace",
        )
        result["workspace_id"] = workspace_id
        result["workspace_path"] = str(source)
        return result

    def status(self) -> JsonObject:
        usage = shutil.disk_usage(self.workspace_root)
        states: dict[str, int] = {}
        for job in self._jobs.values():
            states[job.state] = states.get(job.state, 0) + 1
        tool_names = (
            "bash",
            "git",
            "ssh",
            "curl",
            "wget",
            "rg",
            "make",
            "gcc",
            "g++",
            "cmake",
            "ninja",
            "python",
            "uv",
            "picocom",
        )
        return {
            "uid": os.getuid(),
            "gid": os.getgid(),
            "home": str(self.home),
            "workspace_root": str(self.workspace_root),
            "shell": self.settings.shell,
            "workspaces": self.workspace_list()["count"],
            "jobs": states,
            "disk": {
                "total_bytes": usage.total,
                "used_bytes": usage.used,
                "free_bytes": usage.free,
            },
            "tools": {name: shutil.which(name) or "" for name in tool_names},
        }

    def _environment(self, overrides: dict[str, str] | None) -> dict[str, str]:
        env = dict(os.environ)
        env["HOME"] = str(self.home)
        if overrides:
            for key, value in overrides.items():
                if "\x00" in key or "=" in key or not key:
                    raise TerminalError(f"invalid environment variable name: {key!r}")
                if "\x00" in value:
                    raise TerminalError(f"invalid environment value for {key}")
                env[key] = value
        return env

    async def terminal_exec(
        self,
        workspace_id: str,
        command: str,
        cwd: str = "",
        env: dict[str, str] | None = None,
        timeout_seconds: float = 60,
        max_output_bytes: int | None = None,
    ) -> JsonObject:
        if not command.strip():
            raise TerminalError("command is required")
        workspace_id = self._workspace_id(workspace_id)
        workdir = self.resolve_cwd(workspace_id, cwd)
        requested_limit = max_output_bytes or self.settings.max_exec_output_bytes
        if requested_limit <= 0:
            raise TerminalError("max_output_bytes must be > 0")
        limit = min(requested_limit, self.settings.max_exec_output_bytes)
        started = time.time()
        process = await asyncio.create_subprocess_shell(
            command,
            executable=self.settings.shell,
            cwd=workdir,
            env=self._environment(env),
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )
        timed_out = False
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=max(0.1, timeout_seconds),
            )
        except TimeoutError:
            timed_out = True
            self._signal_process_group(process.pid, signal.SIGTERM)
            try:
                stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=2)
            except TimeoutError:
                self._signal_process_group(process.pid, signal.SIGKILL)
                stdout, stderr = await process.communicate()
        ended = time.time()
        stdout_value, stdout_truncated = self._decode_bounded(stdout, limit)
        stderr_value, stderr_truncated = self._decode_bounded(stderr, limit)
        return {
            "workspace_id": workspace_id,
            "command": command,
            "cwd": str(workdir),
            "exit_code": process.returncode,
            "timed_out": timed_out,
            "stdout": stdout_value,
            "stderr": stderr_value,
            "stdout_truncated": stdout_truncated,
            "stderr_truncated": stderr_truncated,
            "started_at": _timestamp(started),
            "ended_at": _timestamp(ended),
            "duration_seconds": round(ended - started, 3),
        }

    @staticmethod
    def _decode_bounded(value: bytes, limit: int) -> tuple[str, bool]:
        truncated = len(value) > limit
        data = value[:limit]
        return data.decode("utf-8", errors="replace"), truncated

    def _job_dir(self, job_id: str) -> Path:
        return self.jobs_root / job_id

    def _persist(self, job: Job) -> None:
        job.metadata_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "job_id": job.job_id,
            "workspace_id": job.workspace_id,
            "command": job.command,
            "cwd": job.cwd,
            "interactive": job.interactive,
            "label": job.label,
            "state": job.state,
            "created_at": job.created_at,
            "started_at": job.started_at,
            "ended_at": job.ended_at,
            "exit_code": job.exit_code,
            "signal_number": job.signal_number,
            "pid": job.pid,
            "log_path": str(job.log_path),
            "log_truncated": job.log_truncated,
        }
        tmp = job.metadata_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(job.metadata_path)

    def _load_persisted_jobs(self) -> None:
        for metadata_path in sorted(self.jobs_root.glob("*/metadata.json")):
            try:
                data = json.loads(metadata_path.read_text(encoding="utf-8"))
                state = str(data.get("state", "unknown"))
                ended_at = data.get("ended_at")
                if state in {"running", "cancelling"}:
                    state = "interrupted"
                    ended_at = time.time()
                job = Job(
                    job_id=str(data["job_id"]),
                    workspace_id=str(data["workspace_id"]),
                    command=str(data.get("command", "")),
                    cwd=str(data.get("cwd", "")),
                    interactive=bool(data.get("interactive", False)),
                    label=str(data.get("label", "")),
                    state=state,
                    created_at=float(data.get("created_at", 0)),
                    started_at=float(data.get("started_at", 0)),
                    ended_at=float(ended_at) if ended_at is not None else None,
                    exit_code=data.get("exit_code"),
                    signal_number=data.get("signal_number"),
                    pid=data.get("pid"),
                    log_path=Path(data.get("log_path") or metadata_path.parent / "output.log"),
                    metadata_path=metadata_path,
                    log_truncated=bool(data.get("log_truncated", False)),
                )
                self._jobs[job.job_id] = job
                self._persist(job)
            except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
                continue

    async def job_start(
        self,
        workspace_id: str,
        command: str,
        cwd: str = "",
        env: dict[str, str] | None = None,
        interactive: bool = False,
        label: str = "",
        cols: int = 120,
        rows: int = 40,
    ) -> JsonObject:
        if not command.strip():
            raise TerminalError("command is required")
        workspace_id = self._workspace_id(workspace_id)
        workdir = self.resolve_cwd(workspace_id, cwd)
        job_id = uuid.uuid4().hex
        job_dir = self._job_dir(job_id)
        job_dir.mkdir(parents=True, exist_ok=False)
        log_path = job_dir / "output.log"
        log_path.touch()
        metadata_path = job_dir / "metadata.json"
        now = time.time()

        if interactive:
            master_fd, slave_fd = pty.openpty()
            self._resize_fd(master_fd, cols, rows)
            try:
                process = await asyncio.create_subprocess_shell(
                    command,
                    executable=self.settings.shell,
                    cwd=workdir,
                    env=self._environment(env),
                    stdin=slave_fd,
                    stdout=slave_fd,
                    stderr=slave_fd,
                    start_new_session=True,
                )
            finally:
                os.close(slave_fd)
        else:
            master_fd = None
            process = await asyncio.create_subprocess_shell(
                command,
                executable=self.settings.shell,
                cwd=workdir,
                env=self._environment(env),
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                start_new_session=True,
            )

        job = Job(
            job_id=job_id,
            workspace_id=workspace_id,
            command=command,
            cwd=str(workdir),
            interactive=interactive,
            label=label,
            state="running",
            created_at=now,
            started_at=now,
            ended_at=None,
            exit_code=None,
            signal_number=None,
            pid=process.pid,
            log_path=log_path,
            metadata_path=metadata_path,
            process=process,
            master_fd=master_fd,
        )
        self._jobs[job_id] = job
        self._persist(job)
        job.reader_task = asyncio.create_task(self._read_job_output(job))
        job.watcher_task = asyncio.create_task(self._watch_job(job))
        return self._job_public(job)

    async def _read_job_output(self, job: Job) -> None:
        try:
            if job.interactive:
                assert job.master_fd is not None
                while True:
                    try:
                        chunk = await asyncio.to_thread(os.read, job.master_fd, 65536)
                    except OSError:
                        break
                    if not chunk:
                        break
                    self._append_job_output(job, chunk)
            else:
                assert job.process is not None
                assert job.process.stdout is not None
                while True:
                    chunk = await job.process.stdout.read(65536)
                    if not chunk:
                        break
                    self._append_job_output(job, chunk)
        finally:
            if job.master_fd is not None:
                try:
                    os.close(job.master_fd)
                except OSError:
                    pass
                job.master_fd = None

    def _append_job_output(self, job: Job, chunk: bytes) -> None:
        try:
            size = job.log_path.stat().st_size
        except FileNotFoundError:
            size = 0
        remaining = max(0, self.settings.max_job_log_bytes - size)
        if remaining <= 0:
            if not job.log_truncated:
                job.log_truncated = True
                self._persist(job)
            return
        data = chunk[:remaining]
        with job.log_path.open("ab") as stream:
            stream.write(data)
        if len(data) < len(chunk):
            job.log_truncated = True
            self._persist(job)

    async def _watch_job(self, job: Job) -> None:
        assert job.process is not None
        returncode = await job.process.wait()
        if job.reader_task is not None:
            try:
                await job.reader_task
            except Exception:
                pass
        job.ended_at = time.time()
        job.exit_code = returncode
        job.signal_number = -returncode if returncode < 0 else None
        if job.state == "cancelling":
            job.state = "cancelled"
        elif returncode == 0:
            job.state = "completed"
        else:
            job.state = "failed"
        job.pid = None
        job.process = None
        self._persist(job)

    def _get_job(self, job_id: str) -> Job:
        job = self._jobs.get(job_id.strip())
        if job is None:
            raise TerminalError(f"job not found: {job_id}")
        return job

    def _job_public(self, job: Job) -> JsonObject:
        try:
            output_bytes = job.log_path.stat().st_size
        except FileNotFoundError:
            output_bytes = 0
        return {
            "job_id": job.job_id,
            "workspace_id": job.workspace_id,
            "label": job.label,
            "command": job.command,
            "cwd": job.cwd,
            "interactive": job.interactive,
            "state": job.state,
            "pid": job.pid,
            "exit_code": job.exit_code,
            "signal": job.signal_number,
            "created_at": _timestamp(job.created_at),
            "started_at": _timestamp(job.started_at),
            "ended_at": _timestamp(job.ended_at),
            "duration_seconds": round(
                (job.ended_at or time.time()) - job.started_at,
                3,
            ),
            "output_bytes": output_bytes,
            "output_truncated": job.log_truncated,
        }

    def job_status(self, job_id: str) -> JsonObject:
        return self._job_public(self._get_job(job_id))

    def job_list(self, workspace_id: str = "", state: str = "") -> JsonObject:
        workspace = workspace_id.strip()
        if workspace:
            self._require_workspace(workspace)
        state_filter = state.strip()
        jobs = [
            self._job_public(job)
            for job in sorted(self._jobs.values(), key=lambda item: item.created_at, reverse=True)
            if (not workspace or job.workspace_id == workspace)
            and (not state_filter or job.state == state_filter)
        ]
        return {"jobs": jobs, "count": len(jobs)}

    async def job_read(
        self,
        job_id: str,
        cursor: int = 0,
        max_bytes: int | None = None,
        wait_seconds: float = 0,
    ) -> JsonObject:
        job = self._get_job(job_id)
        if cursor < 0:
            raise TerminalError("cursor must be >= 0")
        requested_limit = max_bytes or self.settings.max_job_read_bytes
        if requested_limit <= 0:
            raise TerminalError("max_bytes must be > 0")
        limit = min(requested_limit, self.settings.max_job_read_bytes)
        deadline = time.monotonic() + max(0, min(wait_seconds, 30))
        while True:
            try:
                size = job.log_path.stat().st_size
            except FileNotFoundError:
                size = 0
            if size > cursor or job.state not in {"running", "cancelling"}:
                break
            if time.monotonic() >= deadline:
                break
            await asyncio.sleep(0.05)

        if cursor > size:
            raise TerminalError(
                f"cursor {cursor} is beyond retained output size {size}"
            )
        with job.log_path.open("rb") as stream:
            stream.seek(cursor)
            data = stream.read(limit)
        next_cursor = cursor + len(data)
        return {
            "job_id": job.job_id,
            "cursor": cursor,
            "next_cursor": next_cursor,
            "output": data.decode("utf-8", errors="replace"),
            "total_output_bytes": size,
            "state": job.state,
            "eof": job.state not in {"running", "cancelling"} and next_cursor >= size,
            "output_truncated": job.log_truncated,
        }

    def job_write(self, job_id: str, data: str) -> JsonObject:
        job = self._get_job(job_id)
        if not job.interactive:
            raise TerminalError("job is not interactive")
        if job.state != "running" or job.master_fd is None:
            raise TerminalError(f"interactive job is not running: {job.state}")
        written = os.write(job.master_fd, data.encode("utf-8"))
        return {"job_id": job.job_id, "written_bytes": written}

    def job_resize(self, job_id: str, cols: int, rows: int) -> JsonObject:
        job = self._get_job(job_id)
        if not job.interactive:
            raise TerminalError("job is not interactive")
        if job.master_fd is None:
            raise TerminalError("interactive job is not running")
        self._resize_fd(job.master_fd, cols, rows)
        return {"job_id": job.job_id, "cols": cols, "rows": rows}

    @staticmethod
    def _resize_fd(fd: int, cols: int, rows: int) -> None:
        if not 1 <= cols <= 1000 or not 1 <= rows <= 1000:
            raise TerminalError("terminal size must be between 1 and 1000")
        fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))

    async def job_wait(self, job_id: str, timeout_seconds: float = 30) -> JsonObject:
        job = self._get_job(job_id)
        if job.watcher_task is not None and job.state in {"running", "cancelling"}:
            try:
                await asyncio.wait_for(
                    asyncio.shield(job.watcher_task),
                    timeout=max(0, min(timeout_seconds, 300)),
                )
            except TimeoutError:
                pass
        return self._job_public(job)

    async def job_cancel(self, job_id: str, grace_seconds: float = 3) -> JsonObject:
        job = self._get_job(job_id)
        process = job.process
        if process is None or job.state not in {"running", "cancelling"}:
            return self._job_public(job)
        job.state = "cancelling"
        self._persist(job)
        self._signal_process_group(process.pid, signal.SIGTERM)
        try:
            await asyncio.wait_for(
                asyncio.shield(process.wait()),
                timeout=max(0.1, min(grace_seconds, 30)),
            )
        except TimeoutError:
            self._signal_process_group(process.pid, signal.SIGKILL)
            await process.wait()
        if job.watcher_task is not None:
            try:
                await asyncio.wait_for(asyncio.shield(job.watcher_task), timeout=2)
            except TimeoutError:
                pass
        return self._job_public(job)

    @staticmethod
    def _signal_process_group(pid: int | None, signum: signal.Signals) -> None:
        if pid is None:
            return
        try:
            os.killpg(pid, signum)
        except ProcessLookupError:
            pass
