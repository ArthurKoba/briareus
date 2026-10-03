from __future__ import annotations

import json
import ssl
import urllib.error
import urllib.parse
import urllib.request

from opentelemetry import trace
from opentelemetry.trace import SpanKind

from common.account_contracts import ResolvedAccount
from common.models import JsonObject, JsonValue, json_loads, json_object

_TRACER = trace.get_tracer("mcp-bridge.provider.signoz")


class SigNozClientError(RuntimeError):
    pass


class SigNozClient:
    def __init__(self, account: ResolvedAccount, *, timeout_seconds: float = 30.0) -> None:
        self.account = account
        self.base_url = account.base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def _context(self) -> ssl.SSLContext | None:
        parsed = urllib.parse.urlsplit(self.base_url)
        if parsed.scheme != "https":
            return None
        if not self.account.verify_tls:
            return ssl._create_unverified_context()
        if self.account.ca_cert_pem:
            return ssl.create_default_context(cadata=self.account.ca_cert_pem.replace("\\n", "\n"))
        return ssl.create_default_context()

    def _request(
        self,
        method: str,
        path: str,
        *,
        query: dict[str, str] | None = None,
        payload: JsonObject | None = None,
    ) -> JsonValue:
        target = self.base_url + path
        if query:
            target += "?" + urllib.parse.urlencode(query)
        body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode()
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "SIGNOZ-API-KEY": self.account.credential,
            "User-Agent": "mcp-bridge-signoz",
        }
        request = urllib.request.Request(target, data=body, method=method, headers=headers)
        with _TRACER.start_as_current_span(
            "provider.signoz.http",
            kind=SpanKind.CLIENT,
            attributes={
                "mcp.provider": "signoz",
                "http.request.method": method,
            },
        ) as span:
            try:
                with urllib.request.urlopen(
                    request,
                    timeout=self.timeout_seconds,
                    context=self._context(),
                ) as response:
                    raw = response.read()
                    span.set_attribute("http.response.status_code", response.status)
                    span.set_attribute("http.response.body.size", len(raw))
            except urllib.error.HTTPError as exc:
                span.set_attribute("http.response.status_code", exc.code)
                detail = exc.read()[:4096].decode("utf-8", "replace")
                raise SigNozClientError(f"SigNoz HTTP {exc.code}: {detail}") from exc
            except urllib.error.URLError as exc:
                raise SigNozClientError(f"SigNoz transport error: {exc.reason}") from exc
        return json_loads(raw, context="SigNoz response")

    def whoami(self) -> JsonObject:
        return json_object(
            self._request("GET", "/api/v1/service_accounts/me"),
            context="SigNoz service account",
        )

    def query_range(self, payload: JsonObject) -> JsonValue:
        return self._request("POST", "/api/v5/query_range", payload=payload)

    def search_logs(
        self,
        *,
        start_ms: int,
        end_ms: int,
        filter_expression: str = "",
        limit: int = 100,
        offset: int = 0,
    ) -> JsonValue:
        if start_ms <= 0 or end_ms <= start_ms:
            raise ValueError("start_ms and end_ms must define a positive time range")
        if not 1 <= limit <= 500:
            raise ValueError("limit must be between 1 and 500")
        if offset < 0:
            raise ValueError("offset must be >= 0")
        payload = {
            "schemaVersion": "v1",
            "start": start_ms,
            "end": end_ms,
            "requestType": "raw",
            "compositeQuery": {
                "queries": [
                    {
                        "type": "builder_query",
                        "spec": {
                            "name": "A",
                            "signal": "logs",
                            "disabled": False,
                            "filter": {"expression": filter_expression},
                            "limit": limit,
                            "offset": offset,
                            "order": [
                                {"key": {"name": "timestamp"}, "direction": "desc"},
                                {"key": {"name": "id"}, "direction": "desc"},
                            ],
                            "having": {"expression": ""},
                        },
                    }
                ]
            },
            "formatOptions": {"formatTableResultForUI": False, "fillGaps": False},
            "variables": {},
        }
        return self.query_range(json_object(payload, context="SigNoz logs query"))

    def search_traces(
        self,
        *,
        start_ms: int,
        end_ms: int,
        filter_expression: str = "",
        limit: int = 100,
        offset: int = 0,
    ) -> JsonValue:
        if start_ms <= 0 or end_ms <= start_ms:
            raise ValueError("start_ms and end_ms must define a positive time range")
        if not 1 <= limit <= 500:
            raise ValueError("limit must be between 1 and 500")
        if offset < 0:
            raise ValueError("offset must be >= 0")
        fields = [
            ("timestamp", "number", "span"),
            ("trace_id", "string", "span"),
            ("span_id", "string", "span"),
            ("parent_span_id", "string", "span"),
            ("name", "string", "span"),
            ("service.name", "string", "resource"),
            ("kind_string", "string", "span"),
            ("duration_nano", "number", "span"),
            ("has_error", "bool", "span"),
            ("status_code_string", "string", "span"),
            ("status_message", "string", "span"),
            ("response_status_code", "string", "span"),
            ("http_method", "string", "span"),
        ]
        payload = {
            "schemaVersion": "v1",
            "start": start_ms,
            "end": end_ms,
            "requestType": "raw",
            "compositeQuery": {
                "queries": [
                    {
                        "type": "builder_query",
                        "spec": {
                            "name": "A",
                            "signal": "traces",
                            "disabled": False,
                            "filter": {"expression": filter_expression},
                            "limit": limit,
                            "offset": offset,
                            "order": [{"key": {"name": "timestamp"}, "direction": "desc"}],
                            "having": {"expression": ""},
                            "selectFields": [
                                {
                                    "name": name,
                                    "fieldDataType": data_type,
                                    "signal": "traces",
                                    "fieldContext": context,
                                }
                                for name, data_type, context in fields
                            ],
                        },
                    }
                ]
            },
            "formatOptions": {"formatTableResultForUI": False, "fillGaps": False},
            "variables": {},
        }
        return self.query_range(json_object(payload, context="SigNoz traces query"))

    def list_services(self, *, start: str, end: str) -> JsonValue:
        return self._request(
            "POST",
            "/api/v1/services",
            payload={"start": start, "end": end},
        )

    def field_keys(
        self,
        *,
        signal: str,
        search_text: str = "",
        metric_name: str = "",
    ) -> JsonValue:
        query = {"signal": signal}
        if search_text:
            query["searchText"] = search_text
        if metric_name:
            query["metricName"] = metric_name
        return self._request("GET", "/api/v1/fields/keys", query=query)

    def field_values(
        self,
        *,
        signal: str,
        name: str,
        search_text: str = "",
        metric_name: str = "",
    ) -> JsonValue:
        query = {"signal": signal, "name": name}
        if search_text:
            query["searchText"] = search_text
        if metric_name:
            query["metricName"] = metric_name
        return self._request("GET", "/api/v1/fields/values", query=query)

    def account_summary(self) -> JsonObject:
        return json_object(
            {
                **self.account.model_dump(mode="json", exclude={"credential"}),
                "credential_configured": True,
            },
            context="SigNoz account summary",
        )
