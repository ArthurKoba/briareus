from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from opentelemetry.trace import Span

from common.account_contracts import InvocationEvent
from common.observability import (
    CompositeObservabilitySink,
    ManagementAuditSink,
    ObservabilitySink,
    _parse_key_values,
    _resource_attributes,
)
from common.settings import ObservabilitySettings
from common.tool_observability import (
    invocation_arguments_payload,
    invocation_result_payload,
    management_audit_enabled,
)


class _RecordingSink(ObservabilitySink):
    def __init__(self) -> None:
        self.runtime_scopes: list[str] = []
        self.events: list[InvocationEvent] = []
        self.spans: list[tuple[str, dict[str, object]]] = []

    def record_runtime_started(self, scope: str) -> None:
        self.runtime_scopes.append(scope)

    def record_runtime_heartbeat(self, scope: str) -> None:
        self.runtime_scopes.append(f"heartbeat:{scope}")

    def record_invocation(
        self,
        event: InvocationEvent,
        *,
        audit: bool = True,
    ) -> None:
        del audit
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

    def record_invocation(
        self,
        event: InvocationEvent,
        *,
        audit: bool = True,
    ) -> None:
        del event, audit
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


def test_management_audit_can_be_suppressed_for_internal_proxy_calls() -> None:
    class FakeManagement:
        def __init__(self) -> None:
            self.events: list[InvocationEvent] = []

        def record_invocation(self, event: InvocationEvent) -> None:
            self.events.append(event)

    management = FakeManagement()
    sink = ManagementAuditSink(management)  # type: ignore[arg-type]
    event = InvocationEvent(
        module="ghidra",
        tool="list_projects",
        status="success",
        duration_ms=1.0,
    )

    sink.record_invocation(event, audit=False)
    assert management.events == []

    sink.record_invocation(event, audit=True)
    assert management.events == [event]


def test_analysis_and_ghidra_audit_visibility_contract() -> None:
    assert management_audit_enabled("analysis", "") is True
    assert management_audit_enabled("analysis", "analysis") is True
    assert management_audit_enabled("ghidra", "") is True
    assert management_audit_enabled("ghidra", "external-agent") is True
    assert management_audit_enabled("ghidra", "analysis") is False


def test_terminal_management_audit_bounds_commands_and_omits_stream_payloads() -> None:
    arguments = invocation_arguments_payload(
        "terminal",
        {"workspace_id": "demo", "command": "x" * 3000, "data": "secret-ish-input"},
    )
    result = invocation_result_payload(
        "terminal",
        {"stdout": "y" * 100000, "stderr": "", "exit_code": 0},
    )

    assert '"workspace_id": "demo"' in arguments
    assert "<truncated 952 chars>" in arguments
    assert "secret-ish-input" not in arguments
    assert "<omitted 16 chars>" in arguments
    assert "y" * 100 not in result
    assert "terminal result omitted" in result
