from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from opentelemetry.trace import Span

from common.account_contracts import InvocationEvent
from common.observability import (
    CompositeObservabilitySink,
    ObservabilitySink,
    _parse_key_values,
    _resource_attributes,
)
from common.settings import ObservabilitySettings


class _RecordingSink(ObservabilitySink):
    def __init__(self) -> None:
        self.runtime_scopes: list[str] = []
        self.events: list[InvocationEvent] = []
        self.spans: list[tuple[str, dict[str, object]]] = []

    def record_runtime_started(self, scope: str) -> None:
        self.runtime_scopes.append(scope)

    def record_runtime_heartbeat(self, scope: str) -> None:
        self.runtime_scopes.append(f"heartbeat:{scope}")

    def record_invocation(self, event: InvocationEvent) -> None:
        self.events.append(event)

    @contextmanager
    def trace_span(
        self,
        name: str,
        attributes: dict[str, object] | None = None,
    ) -> Iterator[Span | None]:
        self.spans.append((name, attributes or {}))
        yield None


class _FailingSink(ObservabilitySink):
    def record_runtime_started(self, scope: str) -> None:
        del scope
        raise RuntimeError("sink unavailable")

    def record_runtime_heartbeat(self, scope: str) -> None:
        del scope
        raise RuntimeError("sink unavailable")

    def record_invocation(self, event: InvocationEvent) -> None:
        del event
        raise RuntimeError("sink unavailable")

    @contextmanager
    def trace_span(
        self,
        name: str,
        attributes: dict[str, object] | None = None,
    ) -> Iterator[Span | None]:
        del name, attributes
        raise RuntimeError("span unavailable")
        yield None


def test_composite_observability_isolates_sink_failures() -> None:
    recording = _RecordingSink()
    sink = CompositeObservabilitySink([_FailingSink(), recording])
    event = InvocationEvent(
        module="github",
        tool="github_agent_status",
        status="success",
        duration_ms=12.5,
    )

    sink.record_runtime_started("github")
    sink.record_runtime_heartbeat("github")
    sink.record_invocation(event)
    with sink.trace_span("mcp.tool.github_agent_status", {"mcp.scope": "github"}):
        pass

    assert recording.runtime_scopes == ["github", "heartbeat:github"]
    assert recording.events == [event]
    assert recording.spans == [
        ("mcp.tool.github_agent_status", {"mcp.scope": "github"})
    ]


def test_parse_otlp_headers_decodes_percent_encoding() -> None:
    assert _parse_key_values("Authorization=Bearer%20test-token,x-scope=bridge") == {
        "Authorization": "Bearer test-token",
        "x-scope": "bridge",
    }


def test_resource_attributes_are_scoped_and_do_not_include_secrets(
    monkeypatch,
) -> None:
    monkeypatch.setenv("HOSTNAME", "container-123")
    settings = ObservabilitySettings(
        service_name="mcp-bridge",
        service_version="1.2.3",
        environment="production",
        endpoint="https://otel.example.test",
        headers="Authorization=Bearer%20secret",
        resource_attributes="zone=infra",
    )

    attributes = _resource_attributes(settings, "github")

    assert attributes == {
        "zone": "infra",
        "service.name": "mcp-bridge",
        "service.version": "1.2.3",
        "service.instance.id": "container-123",
        "deployment.environment.name": "production",
        "mcp.scope": "github",
    }
    assert "secret" not in repr(attributes)


def test_observability_settings_resolve_all_signal_endpoints() -> None:
    settings = ObservabilitySettings(endpoint="https://otel.example.test/base/")

    assert settings.signal_endpoint("logs") == "https://otel.example.test/base/v1/logs"
    assert settings.signal_endpoint("traces") == "https://otel.example.test/base/v1/traces"
    assert settings.signal_endpoint("metrics") == "https://otel.example.test/base/v1/metrics"


def test_observability_settings_normalize_signal_specific_base() -> None:
    settings = ObservabilitySettings(endpoint="https://otel.example.test/v1/logs")

    assert settings.signal_endpoint("traces") == "https://otel.example.test/v1/traces"


def test_observability_settings_support_signal_overrides() -> None:
    settings = ObservabilitySettings(
        endpoint="https://otel.example.test",
        logs_endpoint_override="https://logs.example.test/intake",
        traces_endpoint_override="https://traces.example.test/intake",
        metrics_endpoint_override="https://metrics.example.test/intake",
    )

    assert settings.signal_endpoint("logs") == "https://logs.example.test/intake"
    assert settings.signal_endpoint("traces") == "https://traces.example.test/intake"
    assert settings.signal_endpoint("metrics") == "https://metrics.example.test/intake"
