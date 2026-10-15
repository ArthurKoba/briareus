"""Exact private-reply decoding with synthetic messages, not trusted peers."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

from files_hand._native_read import NativeFilesReadRequest
from files_hand._read_adapter import FilesMcpReadUnavailable, FilesReadArguments
from files_hand._read_decision import FilesReadDecisionRequest, decode_private_read_decision

PROJECT = UUID("12345678-1234-4234-8234-123456789abc")
SESSION = UUID("12345678-1234-4234-8234-123456789abd")
OPERATION = UUID("12345678-1234-4234-8234-123456789abe")
ACTOR = UUID("12345678-1234-4234-8234-123456789abf")


def main() -> None:
    now = datetime.now(UTC)
    request = NativeFilesReadRequest(
        OPERATION, PROJECT, SESSION, 4, FilesReadArguments("file.txt", 128)
    )
    command = FilesReadDecisionRequest(request, 7, "before_read")
    wire = json.loads(command.wire_body())
    assert wire["expected_resource_revision"] == 7 and wire["max_bytes"] == 128
    assert wire["resource"] == request.selector.decision_resource()
    data = {
        "protocol": "files-read-decision-v1",
        "allowed": True,
        "operation_uuid": str(OPERATION),
        "phase": "before_read",
        "actor_uuid": str(ACTOR),
        "project_uuid": str(PROJECT),
        "agent_session_uuid": str(SESSION),
        "hand": "files",
        "tool": "read_file",
        "action": "files.read",
        "resource": request.selector.decision_resource(),
        "grant_revision": 4,
        "resource_revision": 7,
        "max_bytes": 128,
        "checked_at": now.isoformat(),
        "expires_at": (now + timedelta(seconds=3)).isoformat(),
    }
    before = decode_private_read_decision(
        command=command,
        status=200,
        body=json.dumps(data).encode(),
        expected_actor_uuid=ACTOR,
        now=now,
    )
    after_command = replace(command, phase="after_read")
    after_data = {
        **data,
        "phase": "after_read",
        "checked_at": (now + timedelta(seconds=1)).isoformat(),
        "expires_at": (now + timedelta(seconds=5)).isoformat(),
    }
    after = decode_private_read_decision(
        command=after_command,
        status=200,
        body=json.dumps(after_data).encode(),
        expected_actor_uuid=ACTOR,
        now=now + timedelta(seconds=1),
    )
    assert after.final_deadline(before, now=now + timedelta(seconds=1)) == before.expires_at
    for previous in (
        after,
        replace(before, actor_uuid=PROJECT),
        replace(before, command=replace(command, resource_revision=8)),
    ):
        try:
            after.final_deadline(previous, now=now + timedelta(seconds=1))
        except FilesMcpReadUnavailable:
            pass
        else:
            raise AssertionError("foreign/reordered phase accepted")
    try:
        after.final_deadline(before, now=now + timedelta(seconds=4))
    except FilesMcpReadUnavailable:
        pass
    else:
        raise AssertionError("new phase extended original expiry")
    cases = [
        {**data, "allowed": 1},
        {**data, "allowed": False},
        {**data, "resource_revision": 8},
        {**data, "grant_revision": 5},
        {**data, "max_bytes": 128.0},
        {**data, "max_bytes": 129},
        {**data, "phase": "after_read"},
        {**data, "actor_uuid": str(PROJECT)},
        {**data, "project_uuid": str(SESSION)},
        {**data, "operation_uuid": str(SESSION)},
        {**data, "extra": True},
        {**data, "resource": {**data["resource"], "x": 1}},
        {**data, "checked_at": now.replace(tzinfo=None).isoformat()},
        {**data, "checked_at": (now + timedelta(seconds=1)).isoformat()},
        {**data, "expires_at": now.isoformat()},
        {**data, "expires_at": (now + timedelta(seconds=6)).isoformat()},
    ]
    encoded = [json.dumps(case).encode() for case in cases]
    encoded.extend(
        [b'{"allowed":true}', b"x" * 8193, json.dumps(data).encode()[:-1] + b',"allowed":true}']
    )
    for body in encoded:
        try:
            decode_private_read_decision(
                command=command, status=200, body=body, expected_actor_uuid=ACTOR, now=now
            )
        except FilesMcpReadUnavailable:
            pass
        else:
            raise AssertionError("malformed/stale reply accepted")
    print("FILES_PRIVATE_PHASE_BINDINGS_EXPIRY_AND_STRICT_JSON_PASS")
    print("SYNTHETIC_MESSAGES_NOT_AN_AUTHENTICATED_PERMISSION")


if __name__ == "__main__":
    main()
