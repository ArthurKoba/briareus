from __future__ import annotations

import json

from common.account_contracts import InvocationEvent
from common.observability import CompositeObservabilitySink, OtlpHttpMetricsSink
from common.settings import ObservabilitySettings


class _RecordingSink:
    def __init__(self) -> None:
        self.runtime_scopes: list[str] = []
        self.events: list[InvocationEvent] = []

    def record_runtime_started(self, scope: str) -> None:
        self.runtime_scopes.append(scope)

    def record_runtime_heartbeat(self, scope: str) -> None:
        self.runtime_scopes.append(f"heartbeat:{scope}")

    def record_invocation(self, event: InvocationEvent) -> None:
        self.events.append(event)


class _FailingSink:
    def record_runtime_started(self, scope: str) -> None:
        del scope
        raise RuntimeError("sink unavailable")

    def record_runtime_heartbeat(self, scope: str) -> None:
        del scope
        raise RuntimeError("sink unavailable")

    def record_invocation(self, event: InvocationEvent) -> None:
        del event
        raise RuntimeError("sink unavailable")


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

    assert recording.runtime_scopes == ["github", "heartbeat:github"]
    assert recording.events == [event]


def test_otlp_metrics_sink_uses_service_and_scope_without_payloads(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class Response:
        def __init__(self) -> None:
            self.headers: dict[str, str] = {}

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

        def read(self, size: int = -1) -> bytes:
            del size
            return b"{}"

    def fake_urlopen(request, timeout: float):
        captured["request"] = request
        captured["timeout"] = timeout
        return Response()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    settings = ObservabilitySettings(
        service_name="mcp-bridge",
        endpoint="https://telemetry.kobanexus.ru",
        headers="Authorization=Bearer%20test-token",
        resource_attributes="deployment.environment.name=production",
        timeout_ms=2500,
    )
    sink = OtlpHttpMetricsSink("github", settings)
    sink.record_invocation(
        InvocationEvent(
            request_id="request-1",
            module="github",
            tool="github_reviewer_merge_pull_request",
            account_id="secret-account-id",
            provider="github",
            status="error",
            duration_ms=42.25,
            error_type="GitHubAgentError",
            arguments_json='{"token":"do-not-export"}',
            result_json='{"secret":"do-not-export"}',
            error_message="do-not-export",
        )
    )

    request = captured["request"]
    assert request.full_url == "https://telemetry.kobanexus.ru/v1/metrics"
    assert request.headers["Authorization"] == "Bearer test-token"
    assert captured["timeout"] == 2.5

    payload = json.loads(request.data)
    encoded = json.dumps(payload)
    assert "do-not-export" not in encoded
    assert "secret-account-id" not in encoded

    resource = payload["resourceMetrics"][0]
    attributes = {
        item["key"]: next(iter(item["value"].values()))
        for item in resource["resource"]["attributes"]
    }
    assert attributes["service.name"] == "mcp-bridge"
    assert attributes["mcp.scope"] == "github"
    assert attributes["deployment.environment.name"] == "production"
    assert resource["scopeMetrics"][0]["scope"]["name"] == "mcp-bridge.github"

    metric_names = {
        metric["name"]
        for metric in resource["scopeMetrics"][0]["metrics"]
    }
    assert metric_names == {
        "mcp.tool.calls",
        "mcp.tool.duration",
        "mcp.tool.errors",
    }


def test_observability_settings_support_exact_metrics_endpoint() -> None:
    settings = ObservabilitySettings(
        endpoint="https://collector.example/base",
        metrics_endpoint_override="https://collector.example/custom/metrics",
    )

    assert settings.enabled is True
    assert settings.metrics_endpoint == "https://collector.example/custom/metrics"
