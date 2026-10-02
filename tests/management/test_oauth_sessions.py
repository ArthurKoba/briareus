from __future__ import annotations

from datetime import UTC, datetime, timedelta

from common.oauth_session_contracts import OAuthSessionEvent
from management.application.services import OAuthSessionService
from management.infrastructure.database import Base, OAuthSessionRecord, create_database
from management.infrastructure.repositories import SqlAlchemyOAuthSessionRepository


def test_oauth_session_events_track_rotation_activity_and_errors(tmp_path) -> None:
    engine, sessions = create_database(f"sqlite:///{tmp_path / 'sessions.sqlite3'}")
    Base.metadata.create_all(engine)
    service = OAuthSessionService(SqlAlchemyOAuthSessionRepository(sessions))
    now = datetime.now(UTC)

    created = service.record(
        OAuthSessionEvent(
            session_id="upstream-session-1",
            client_id="chatgpt-client",
            client_name="ChatGPT",
            resource="https://mcp.example.test/web/mcp",
            login="arthurkoba",
            subject="42",
            scopes=["read:user"],
            status="active",
            event="authorized",
            access_jti="access-1",
            refresh_jti="refresh-1",
            access_expires_at=now + timedelta(hours=24),
            refresh_expires_at=now + timedelta(days=30),
            occurred_at=now,
        )
    )
    assert created.status == "active"
    assert created.refresh_jti == "refresh-1"
    assert created.last_used_at == now

    refreshed_at = now + timedelta(minutes=5)
    refreshed = service.record(
        OAuthSessionEvent(
            session_id="upstream-session-1",
            client_id="chatgpt-client",
            resource="https://mcp.example.test/web/mcp",
            status="active",
            event="refresh_success",
            access_jti="access-2",
            refresh_jti="refresh-2",
            occurred_at=refreshed_at,
        )
    )
    assert refreshed.refresh_jti == "refresh-2"
    assert refreshed.previous_refresh_jti == "refresh-1"
    assert refreshed.last_refresh_at == refreshed_at

    recovered_at = refreshed_at + timedelta(seconds=1)
    recovered = service.record(
        OAuthSessionEvent(
            session_id="upstream-session-1",
            client_id="chatgpt-client",
            resource="https://mcp.example.test/web/mcp",
            status="active",
            event="refresh_success_after_upstream_race",
            access_jti="access-3",
            refresh_jti="refresh-3",
            occurred_at=recovered_at,
        )
    )
    assert recovered.last_refresh_at == recovered_at
    assert recovered.last_used_at == recovered_at
    assert recovered.previous_refresh_jti == "refresh-2"

    error_at = recovered_at + timedelta(seconds=1)
    failed = service.record(
        OAuthSessionEvent(
            client_id="chatgpt-client",
            resource="https://mcp.example.test/web/mcp",
            status="invalid",
            event="refresh_missing",
            refresh_jti="refresh-1",
            error_type="invalid_grant",
            error_message="old token retried after rotation",
            occurred_at=error_at,
        )
    )
    assert failed.id == "upstream-session-1"
    assert failed.status == "invalid"
    assert failed.error_type == "invalid_grant"
    assert failed.last_event == "refresh_missing"

    with sessions() as session:
        rows = session.query(OAuthSessionRecord).all()
        assert len(rows) == 1
    engine.dispose()


def test_gateway_observation_merges_with_later_auth_refresh(tmp_path) -> None:
    engine, sessions = create_database(f"sqlite:///{tmp_path / 'legacy.sqlite3'}")
    Base.metadata.create_all(engine)
    service = OAuthSessionService(SqlAlchemyOAuthSessionRepository(sessions))
    now = datetime.now(UTC)

    observed = service.record(
        OAuthSessionEvent(
            client_id="chatgpt-client",
            resource="https://mcp.example.test/web/mcp",
            login="arthurkoba",
            status="active",
            event="access_used",
            access_jti="legacy-access",
            occurred_at=now,
        )
    )
    assert observed.id.startswith("observed-")

    refreshed = service.record(
        OAuthSessionEvent(
            session_id="upstream-session-real",
            client_id="chatgpt-client",
            resource="https://mcp.example.test/web/mcp",
            login="arthurkoba",
            status="active",
            event="refresh_success",
            access_jti="new-access",
            refresh_jti="new-refresh",
            occurred_at=now + timedelta(minutes=1),
        )
    )

    assert refreshed.id == observed.id
    assert refreshed.access_jti == "new-access"
    assert refreshed.refresh_jti == "new-refresh"
    with sessions() as session:
        assert session.query(OAuthSessionRecord).count() == 1
    engine.dispose()


def test_oauth_session_event_accepts_json_iso_datetimes() -> None:
    event = OAuthSessionEvent.model_validate(
        {
            "client_id": "chatgpt-client",
            "resource": "https://mcp.example.test/web/mcp",
            "status": "active",
            "event": "access_used",
            "access_expires_at": "2026-10-02T07:29:01Z",
            "occurred_at": "2026-10-01T17:15:56.221092Z",
        }
    )
    assert event.access_expires_at is not None
    assert event.access_expires_at.tzinfo is not None
    assert event.occurred_at.tzinfo is not None
