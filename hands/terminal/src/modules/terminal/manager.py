from __future__ import annotations

import asyncio
import fcntl
import grp
import json
import logging
import math
import os
import pty
import re
import shutil
import signal
import stat
import struct
import termios
import time
import uuid
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from common.admin_api_client import AdminApiClient, AdminApiClientError
from common.models import JsonObject, JsonValue
from common.runtime_policy_contracts import TerminalRuntimePolicy
from common.settings import TerminalSettings

logger = logging.getLogger(__name__)

_WORKSPACE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")

_DRAIN_GRACE_SECONDS = 2.0


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
    timeout_seconds: float = 0
    cancel_lock: asyncio.Lock = field(default_factory=asyncio.Lock)


def _timestamp(value: float | None) -> str | None:
    if value is None:
        return None
    return datetime.fromtimestamp(value, UTC).isoformat()


class TerminalManager:
    def __init__(
        self,
        settings: TerminalSettings,
        admin_api: AdminApiClient | None = None,
    ) -> None:
        self.settings = settings
        self.admin_api = admin_api
        self.workspace_root = settings.workspace_root
        self.projects_root = self.workspace_root / "projects"
        self.home = settings.home
        self.jobs_root = self.home / ".terminal" / "jobs"
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
        items: list[JsonValue] = []
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

    @staticmethod
    def _tree_size_bytes(path: Path) -> int:
        total = 0
        stack = [path]
        while stack:
            current = stack.pop()
            try:
                with os.scandir(current) as iterator:
                    for item in iterator:
                        try:
                            if item.is_symlink():
                                continue
                            if item.is_dir(follow_symlinks=False):
                                stack.append(Path(item.path))
                            elif item.is_file(follow_symlinks=False):
                                total += item.stat(follow_symlinks=False).st_size
                        except FileNotFoundError:
                            continue
            except FileNotFoundError:
                continue
        return total

    async def workspace_delete(self, workspace_id: str, force: bool = False) -> JsonObject:
        workspace_id = self._workspace_id(workspace_id)
        path = self._require_workspace(workspace_id)
        active = [
            job
            for job in self._jobs.values()
            if job.workspace_id == workspace_id and job.state in {"running", "cancelling"}
        ]
        size_bytes = self._tree_size_bytes(path)
        logger.info(
            "workspace cleanup decision workspace_id=%s action=delete reason=%s "
            "active_jobs=%d size_bytes=%d",
            workspace_id,
            "forced_manual_delete" if force else "manual_delete",
            len(active),
            size_bytes,
        )
        if active and not force:
            logger.info(
                "workspace cleanup skipped workspace_id=%s reason=active_jobs active_jobs=%d",
                workspace_id,
                len(active),
            )
            raise TerminalError(
                "workspace has active jobs: " + ", ".join(job.job_id for job in active)
            )
        if force:
            for job in active:
                await self.job_cancel(job.job_id, grace_seconds=1)
        shutil.rmtree(path)
        logger.info(
            "workspace cleanup completed workspace_id=%s reason=%s freed_bytes=%d",
            workspace_id,
            "forced_manual_delete" if force else "manual_delete",
            size_bytes,
        )
        return {
            "workspace_id": workspace_id,
            "deleted": True,
            "freed_bytes": size_bytes,
            "reason": "forced_manual_delete" if force else "manual_delete",
        }

    def status(self) -> JsonObject:
        usage = shutil.disk_usage(self.workspace_root)
        states: dict[str, int] = {}
        for job in self._jobs.values():
            states[job.state] = states.get(job.state, 0) + 1
        job_states: JsonObject = {}
        for key, value in states.items():
            job_states[key] = value
        tool_names = (
            "bash",
            "git",
            "gh",
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
            "gdb",
            "strace",
            "socat",
        )
        group_ids = sorted(set(os.getgroups()) | {os.getgid()})
        groups: list[JsonValue] = []
        for group_id in group_ids:
            try:
                name = grp.getgrgid(group_id).gr_name
            except KeyError:
                name = ""
            groups.append({"gid": group_id, "name": name})
        serial_paths = sorted(
            {
                *Path("/dev").glob("ttyUSB*"),
                *Path("/dev").glob("ttyACM*"),
                *Path("/dev/serial/by-id").glob("*"),
            },
            key=str,
        )
        serial_devices: list[JsonValue] = [
            {
                "path": str(path),
                "readable": os.access(path, os.R_OK),
                "writable": os.access(path, os.W_OK),
            }
            for path in serial_paths
        ]
        ssh_dir = self.home / ".ssh"
        public_keys: list[JsonValue] = []
        if ssh_dir.is_dir():
            public_keys.extend(sorted(path.name for path in ssh_dir.glob("*.pub")))
        return {
            "uid": os.getuid(),
            "gid": os.getgid(),
            "groups": groups,
            "home": str(self.home),
            "workspace_root": str(self.workspace_root),
            "shell": self.settings.shell,
            "workspaces": self.workspace_list()["count"],
            "jobs": job_states,
            "disk": {
                "total_bytes": usage.total,
                "used_bytes": usage.used,
                "free_bytes": usage.free,
            },
            "tools": {
                name: shutil.which(name, path=self.settings.path) or "" for name in tool_names
            },
            "serial_devices": serial_devices,
            "ssh_public_keys": public_keys,
            "git_configured": (self.home / ".gitconfig").is_file(),
        }

    def _runtime_policy(self) -> TerminalRuntimePolicy:
        if self.admin_api is None:
            return TerminalRuntimePolicy()
        try:
            return self.admin_api.terminal_runtime_policy()
        except (AdminApiClientError, ValueError):
            return TerminalRuntimePolicy()

    def _environment(self, overrides: dict[str, str] | None) -> dict[str, str]:
        env = {
            "HOME": str(self.home),
            "PATH": self.settings.path,
            "LANG": self.settings.lang,
            "TERM": self.settings.term,
        }
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
        policy = self._runtime_policy()
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise TerminalError("timeout_seconds must be finite and positive")
        effective_timeout = min(
            max(0.1, timeout_seconds),
            float(policy.max_exec_timeout_seconds),
        )
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
        assert process.stdout is not None
        assert process.stderr is not None
        stdout_task = asyncio.create_task(self._drain_bounded(process.stdout, limit))
        stderr_task = asyncio.create_task(self._drain_bounded(process.stderr, limit))
        timed_out = False
        try:
            await asyncio.wait_for(
                process.wait(),
                timeout=effective_timeout,
            )
        except TimeoutError:
            timed_out = True
            await self._terminate_process(process)
        except asyncio.CancelledError:
            try:
                await self._terminate_process(process)
            finally:
                # Even if process termination fails, close both output tasks;
                # leaving inherited pipes open can strand a cancelled call.
                stdout_task.cancel()
                stderr_task.cancel()
                await asyncio.gather(stdout_task, stderr_task, return_exceptions=True)
            raise
        # A shell can exit while a detached descendant still owns stdout or
        # stderr. Never wait indefinitely for pipe EOF after the root exited.
        streams = asyncio.gather(stdout_task, stderr_task)
        try:
            await asyncio.wait_for(asyncio.shield(streams), timeout=_DRAIN_GRACE_SECONDS)
        except TimeoutError:
            stdout_task.cancel()
            stderr_task.cancel()
        (stdout, stdout_truncated), (stderr, stderr_truncated) = await streams
        ended = time.time()
        stdout_value = stdout.decode("utf-8", errors="replace")
        stderr_value = stderr.decode("utf-8", errors="replace")
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
            "timeout_seconds": effective_timeout,
        }

    async def _terminate_process(self, process: asyncio.subprocess.Process) -> None:
        if process.returncode is not None:
            return
        if process.returncode is None:
            self._signal_process_group(process.pid, signal.SIGTERM)
        try:
            await asyncio.wait_for(process.wait(), timeout=2)
        except TimeoutError:
            if process.returncode is None:
                self._signal_process_group(process.pid, signal.SIGKILL)
            await process.wait()
        # Do not signal a numeric PGID *after* the reaped leader exits:
        # PID reuse can make that PGID belong to an unrelated process group.
        # Detached descendants need a real cgroup/process supervisor.

    @staticmethod
    async def _drain_bounded(
        stream: asyncio.StreamReader,
        limit: int,
    ) -> tuple[bytes, bool]:
        buffer = bytearray()
        truncated = False
        try:
            while True:
                chunk = await stream.read(65536)
                if not chunk:
                    break
                remaining = max(0, limit - len(buffer))
                if remaining:
                    buffer.extend(chunk[:remaining])
                if len(chunk) > remaining:
                    truncated = True
        except asyncio.CancelledError:
            # Preserve already collected output; a detached writer may hold
            # the descriptor forever, even after the shell has been reaped.
            truncated = True
        return bytes(buffer), truncated

    def _job_dir(self, job_id: str) -> Path:
        return self.jobs_root / job_id

    @staticmethod
    def _open_owned_job_file(folder: Path, name: str, flags: int) -> int:
        """Pin one regular job file beneath a non-symlink owner directory."""
        if name not in {"metadata.json", "output.log"}:
            raise TerminalError("job file name is not recognized")
        directory = os.open(folder, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        try:
            owner = os.fstat(directory)
            if owner.st_uid != os.geteuid() or not stat.S_ISDIR(owner.st_mode):
                raise TerminalError("job metadata directory owner invalid")
            fd = os.open(name, flags | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=directory)
            try:
                info = os.fstat(fd)
                if (
                    not stat.S_ISREG(info.st_mode)
                    or info.st_uid != owner.st_uid
                    or info.st_dev != owner.st_dev
                    or info.st_nlink != 1
                ):
                    raise TerminalError("job log/metadata file owner invalid")
            except BaseException:
                os.close(fd)
                raise
            return fd
        finally:
            os.close(directory)

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
            "timeout_seconds": job.timeout_seconds,
        }
        # Random exclusive temporary leaf + pinned dirfd prevents replacing
        # a predictable .tmp symlink with an out-of-tree file. Atomic rename
        # of an entry never follows the target leaf's symlink.
        folder_fd = os.open(
            job.metadata_path.parent,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
        )
        temporary = f".metadata-{uuid.uuid4().hex}.tmp"
        try:
            if os.fstat(folder_fd).st_uid != os.geteuid():
                raise TerminalError("job metadata owner invalid")
            temporary_fd = os.open(
                temporary,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
                0o600,
                dir_fd=folder_fd,
            )
            try:
                with os.fdopen(temporary_fd, "wb") as stream:
                    stream.write(json.dumps(payload, ensure_ascii=False, indent=2).encode())
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(
                    temporary,
                    "metadata.json",
                    src_dir_fd=folder_fd,
                    dst_dir_fd=folder_fd,
                )
                os.fsync(folder_fd)
            finally:
                with suppress(FileNotFoundError):
                    os.unlink(temporary, dir_fd=folder_fd)
        finally:
            os.close(folder_fd)

    def _load_persisted_jobs(self) -> None:
        for metadata_path in sorted(self.jobs_root.glob("*/metadata.json")):
            try:
                # JSON metadata is a recovery hint, not a trusted path/PGID.
                # A shell sharing our Unix UID can modify its own job files;
                # never follow its saved absolute log path after restart.
                folder = metadata_path.parent
                if (
                    metadata_path.is_symlink()
                    or folder.is_symlink()
                    or not re.fullmatch(r"[0-9a-f]{32}", folder.name)
                ):
                    continue
                log_path = folder / "output.log"
                try:
                    owned_log_fd = self._open_owned_job_file(folder, "output.log", os.O_RDONLY)
                    os.close(owned_log_fd)
                    metadata_fd = self._open_owned_job_file(folder, "metadata.json", os.O_RDONLY)
                    with os.fdopen(metadata_fd, "r", encoding="utf-8") as input_file:
                        if os.fstat(input_file.fileno()).st_size > 1024 * 1024:
                            continue
                        data = json.load(input_file)
                except (OSError, TerminalError):
                    continue
                if data.get("job_id") != folder.name:
                    continue
                workspace_id = self._workspace_id(str(data["workspace_id"]))
                state = str(data.get("state", "unknown"))
                ended_at = data.get("ended_at")
                if state in {"running", "cancelling"}:
                    # A restarted manager cannot prove PID ownership; never
                    # signal or replay the stale process referenced by disk.
                    state = "interrupted"
                    ended_at = time.time()
                    data["pid"] = None
                job = Job(
                    job_id=folder.name,
                    workspace_id=workspace_id,
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
                    # PID ownership never survives service restart, even for
                    # metadata that claimed an active/completed job.
                    pid=None,
                    log_path=log_path,
                    metadata_path=metadata_path,
                    log_truncated=bool(data.get("log_truncated", False)),
                    timeout_seconds=float(data.get("timeout_seconds", 0) or 0),
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
        timeout_seconds: float | None = None,
    ) -> JsonObject:
        if not command.strip():
            raise TerminalError("command is required")
        workspace_id = self._workspace_id(workspace_id)
        workdir = self.resolve_cwd(workspace_id, cwd)
        policy = self._runtime_policy()
        requested_timeout = (
            float(timeout_seconds)
            if timeout_seconds is not None
            else float(policy.max_job_runtime_seconds)
        )
        if not math.isfinite(requested_timeout) or requested_timeout <= 0:
            raise TerminalError("timeout_seconds must be finite and positive")
        effective_timeout = min(max(0.1, requested_timeout), float(policy.max_job_runtime_seconds))
        if interactive and not 1 <= cols <= 1000:
            raise TerminalError("terminal cols must be between 1 and 1000")
        if interactive and not 1 <= rows <= 1000:
            raise TerminalError("terminal rows must be between 1 and 1000")
        environment = self._environment(env)
        now = time.time()
        job_id = uuid.uuid4().hex
        job_dir = self._job_dir(job_id)
        job_dir.mkdir(mode=0o700, parents=True, exist_ok=False)
        log_path = job_dir / "output.log"
        metadata_path = job_dir / "metadata.json"
        master_fd: int | None = None
        slave_fd: int | None = None
        try:
            log_path.touch(exist_ok=False)
            if interactive:
                master_fd, slave_fd = pty.openpty()
                # A PTY reader must be cancellable without stranding an OS
                # thread blocked in a read held open by an exited child.
                os.set_blocking(master_fd, False)
                self._resize_fd(master_fd, cols, rows)
                process = await asyncio.create_subprocess_shell(
                    command,
                    executable=self.settings.shell,
                    cwd=workdir,
                    env=environment,
                    stdin=slave_fd,
                    stdout=slave_fd,
                    stderr=slave_fd,
                    start_new_session=True,
                )
            else:
                process = await asyncio.create_subprocess_shell(
                    command,
                    executable=self.settings.shell,
                    cwd=workdir,
                    env=environment,
                    stdin=asyncio.subprocess.DEVNULL,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                    start_new_session=True,
                )
        except BaseException:
            # Failing to validate PTY size/create a child must not leak FDs
            # or leave an untracked empty job folder in persistent storage.
            if master_fd is not None:
                with suppress(OSError):
                    os.close(master_fd)
            shutil.rmtree(job_dir, ignore_errors=True)
            raise
        finally:
            if slave_fd is not None:
                with suppress(OSError):
                    os.close(slave_fd)

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
            timeout_seconds=effective_timeout,
        )
        self._jobs[job_id] = job
        try:
            self._persist(job)
            job.reader_task = asyncio.create_task(self._read_job_output(job))
            job.watcher_task = asyncio.create_task(self._watch_job(job))
        except BaseException:
            # The shell was already spawned; metadata/scheduling failure
            # must never leave it running without a recoverable Job owner.
            self._jobs.pop(job_id, None)
            try:
                await self._terminate_process(process)
            finally:
                pending = [task for task in (job.reader_task, job.watcher_task) if task is not None]
                for task in pending:
                    task.cancel()
                if pending:
                    await asyncio.gather(*pending, return_exceptions=True)
                if master_fd is not None:
                    with suppress(OSError):
                        os.close(master_fd)
                shutil.rmtree(job_dir, ignore_errors=True)
            raise
        return self._job_public(job)

    async def _read_job_output(self, job: Job) -> None:
        try:
            if job.interactive:
                assert job.master_fd is not None
                while True:
                    try:
                        chunk = os.read(job.master_fd, 65536)
                    except BlockingIOError:
                        await asyncio.sleep(0.05)
                        continue
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
                with suppress(OSError):
                    os.close(job.master_fd)
                job.master_fd = None

    def _append_job_output(self, job: Job, chunk: bytes) -> None:
        with os.fdopen(
            self._open_owned_job_file(job.log_path.parent, "output.log", os.O_WRONLY | os.O_APPEND),
            "ab",
        ) as stream:
            size = os.fstat(stream.fileno()).st_size
            remaining = max(0, self.settings.max_job_log_bytes - size)
            if remaining:
                stream.write(chunk[:remaining])
        if remaining <= 0:
            if not job.log_truncated:
                job.log_truncated = True
                self._persist(job)
            return
        if remaining < len(chunk):
            job.log_truncated = True
            self._persist(job)

    async def _watch_job(self, job: Job) -> None:
        assert job.process is not None
        timed_out = False
        try:
            returncode = await asyncio.wait_for(
                job.process.wait(),
                timeout=max(0.1, job.timeout_seconds),
            )
        except TimeoutError:
            timed_out = True
            async with job.cancel_lock:
                # Timeout supervisor and explicit job_cancel must not send
                # overlapping signals to one numeric process group.
                await self._terminate_process(job.process)
                returncode = await job.process.wait()
        if job.reader_task is not None:
            try:
                await asyncio.wait_for(
                    asyncio.shield(job.reader_task), timeout=_DRAIN_GRACE_SECONDS
                )
            except TimeoutError:
                # Some subprocesses keep output pipes or a PTY alive after
                # the original command exits; do not hang job finalization.
                job.reader_task.cancel()
                job.log_truncated = True
            except Exception:
                job.log_truncated = True
        job.ended_at = time.time()
        job.exit_code = returncode
        job.signal_number = -returncode if returncode < 0 else None
        if timed_out:
            job.state = "timed_out"
        elif job.state == "cancelling":
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
            log_fd = self._open_owned_job_file(job.log_path.parent, "output.log", os.O_RDONLY)
            try:
                output_bytes = os.fstat(log_fd).st_size
            finally:
                os.close(log_fd)
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
            "timeout_seconds": job.timeout_seconds,
        }

    def job_status(self, job_id: str) -> JsonObject:
        return self._job_public(self._get_job(job_id))

    def job_list(
        self,
        workspace_id: str = "",
        state: str = "",
        offset: int = 0,
        limit: int = 100,
    ) -> JsonObject:
        workspace = workspace_id.strip()
        if workspace:
            self._require_workspace(workspace)
        if offset < 0:
            raise TerminalError("offset must be >= 0")
        if not 1 <= limit <= 1000:
            raise TerminalError("limit must be between 1 and 1000")
        state_filter = state.strip()
        matched = [
            job
            for job in sorted(self._jobs.values(), key=lambda item: item.created_at, reverse=True)
            if (not workspace or job.workspace_id == workspace)
            and (not state_filter or job.state == state_filter)
        ]
        selected: list[JsonValue] = [
            self._job_public(job) for job in matched[offset : offset + limit]
        ]
        return {
            "jobs": selected,
            "count": len(selected),
            "total": len(matched),
            "offset": offset,
            "limit": limit,
            "truncated": offset + len(selected) < len(matched),
        }

    def job_delete(
        self,
        job_id: str,
        *,
        reason: str = "explicit_job_delete",
    ) -> JsonObject:
        job = self._get_job(job_id)
        if (
            job.state in {"running", "cancelling"}
            or (job.watcher_task is not None and not job.watcher_task.done())
            or (job.reader_task is not None and not job.reader_task.done())
        ):
            logger.info(
                "job cleanup skipped job_id=%s workspace_id=%s reason=active_job state=%s",
                job.job_id,
                job.workspace_id,
                job.state,
            )
            raise TerminalError("running jobs must be cancelled before deletion")
        size_bytes = self._tree_size_bytes(job.metadata_path.parent)
        with suppress(FileNotFoundError):
            shutil.rmtree(job.metadata_path.parent)
        self._jobs.pop(job.job_id, None)
        logger.info(
            "job cleanup deleted job_id=%s workspace_id=%s reason=%s state=%s freed_bytes=%d",
            job.job_id,
            job.workspace_id,
            reason,
            job.state,
            size_bytes,
        )
        return {
            "job_id": job.job_id,
            "deleted": True,
            "reason": reason,
            "freed_bytes": size_bytes,
        }

    def job_cleanup(
        self,
        older_than_hours: int = 168,
        dry_run: bool = True,
        limit: int = 1000,
    ) -> JsonObject:
        if not 1 <= older_than_hours <= 24 * 3650:
            raise TerminalError("older_than_hours must be between 1 and 87600")
        if not 1 <= limit <= 10000:
            raise TerminalError("limit must be between 1 and 10000")
        cutoff = time.time() - older_than_hours * 3600
        logger.info(
            "job cleanup scan started older_than_hours=%d dry_run=%s limit=%d retained_jobs=%d",
            older_than_hours,
            dry_run,
            limit,
            len(self._jobs),
        )
        candidates = [
            job
            for job in sorted(
                self._jobs.values(),
                key=lambda item: item.ended_at or item.created_at,
            )
            if job.state not in {"running", "cancelling"}
            and (job.ended_at or job.created_at) <= cutoff
        ][:limit]
        ids = [job.job_id for job in candidates]
        candidate_bytes = sum(self._tree_size_bytes(job.metadata_path.parent) for job in candidates)
        for job in candidates:
            age_hours = max(0.0, (time.time() - (job.ended_at or job.created_at)) / 3600)
            logger.info(
                "job cleanup candidate job_id=%s workspace_id=%s reason=retention_expired "
                "state=%s age_hours=%.2f dry_run=%s",
                job.job_id,
                job.workspace_id,
                job.state,
                age_hours,
                dry_run,
            )
        freed_bytes = 0
        if not dry_run:
            for job_id in ids:
                result = self.job_delete(job_id, reason="retention_expired")
                raw = result.get("freed_bytes")
                if isinstance(raw, int):
                    freed_bytes += raw
        logger.info(
            "job cleanup scan completed candidates=%d candidate_bytes=%d deleted=%d "
            "freed_bytes=%d dry_run=%s",
            len(ids),
            candidate_bytes,
            0 if dry_run else len(ids),
            freed_bytes,
            dry_run,
        )
        public_ids: list[JsonValue] = []
        public_ids.extend(ids)
        return {
            "dry_run": dry_run,
            "older_than_hours": older_than_hours,
            "job_ids": public_ids,
            "count": len(ids),
            "candidate_bytes": candidate_bytes,
            "freed_bytes": freed_bytes,
            "reason": "retention_expired",
        }

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
        if not math.isfinite(wait_seconds) or wait_seconds < 0:
            raise TerminalError("wait_seconds must be finite and nonnegative")
        deadline = time.monotonic() + min(wait_seconds, 30)
        while True:
            try:
                fd = self._open_owned_job_file(job.log_path.parent, "output.log", os.O_RDONLY)
                try:
                    size = os.fstat(fd).st_size
                finally:
                    os.close(fd)
            except FileNotFoundError:
                size = 0
            if size > cursor or job.state not in {"running", "cancelling"}:
                break
            if time.monotonic() >= deadline:
                break
            await asyncio.sleep(0.05)

        if cursor > size:
            raise TerminalError(f"cursor {cursor} is beyond retained output size {size}")
        with os.fdopen(
            self._open_owned_job_file(job.log_path.parent, "output.log", os.O_RDONLY), "rb"
        ) as stream:
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
        payload = data.encode("utf-8")
        if len(payload) > min(self.settings.max_job_read_bytes, 1024 * 1024):
            raise TerminalError("interactive input exceeds the bounded PTY write limit")
        # R3 made the PTY nonblocking: EAGAIN is backpressure, not a fatal
        # Terminal error. Partial writes remain visible to the caller.
        try:
            written = os.write(job.master_fd, payload)
        except BlockingIOError:
            written = 0
        return {
            "job_id": job.job_id,
            "written_bytes": written,
            "backpressured": written < len(payload),
        }

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
        if not math.isfinite(timeout_seconds) or timeout_seconds < 0:
            raise TerminalError("timeout_seconds must be finite and nonnegative")
        if job.watcher_task is not None and job.state in {"running", "cancelling"}:
            with suppress(TimeoutError):
                await asyncio.wait_for(
                    asyncio.shield(job.watcher_task),
                    timeout=min(timeout_seconds, 300),
                )
        return self._job_public(job)

    async def job_cancel(self, job_id: str, grace_seconds: float = 3) -> JsonObject:
        job = self._get_job(job_id)
        if not math.isfinite(grace_seconds) or grace_seconds <= 0:
            raise TerminalError("grace_seconds must be finite and positive")
        async with job.cancel_lock:
            process = job.process
            if process is None or job.state not in {"running", "cancelling"}:
                return self._job_public(job)
            if job.state == "running":
                job.state = "cancelling"
                self._persist(job)
            if process.returncode is None:
                self._signal_process_group(process.pid, signal.SIGTERM)
            try:
                await asyncio.wait_for(
                    asyncio.shield(process.wait()),
                    timeout=max(0.1, min(grace_seconds, 30)),
                )
            except TimeoutError:
                if process.returncode is None:
                    self._signal_process_group(process.pid, signal.SIGKILL)
                await process.wait()
        # Do not await the watcher WHILE holding cancel_lock: watcher may be
        # in the same timeout path and need that lock to finish bookkeeping.
        if job.watcher_task is not None:
            with suppress(TimeoutError):
                await asyncio.wait_for(asyncio.shield(job.watcher_task), timeout=2)
        return self._job_public(job)

    @staticmethod
    def _signal_process_group(pid: int | None, signum: signal.Signals) -> None:
        if pid is None:
            return
        with suppress(ProcessLookupError):
            os.killpg(pid, signum)
