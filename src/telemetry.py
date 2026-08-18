"""Honeycomb OpenTelemetry helpers for the API and extract worker.

If HONEYCOMB_API_KEY is unset, providers are no-op and init() returns False.
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Dict, Iterator, Optional

from opentelemetry import metrics, trace
from opentelemetry.metrics import NoOpMeterProvider
from opentelemetry.sdk.resources import Resource
from opentelemetry.trace import NoOpTracerProvider, Status, StatusCode

_TRACER_NAME = "movie-postcredits"
_initialized = False
_enabled = False
_instruments: Dict[str, Any] = {}

request_id_var: ContextVar[Optional[str]] = ContextVar("request_id", default=None)
tmdb_id_var: ContextVar[Optional[int]] = ContextVar("tmdb_id", default=None)


class JsonFormatter(logging.Formatter):
    """JSON logs that include request_id / tmdb_id when bound."""

    def format(self, record: logging.LogRecord) -> str:
        payload: Dict[str, Any] = {
            "time": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        request_id = getattr(record, "request_id", None) or request_id_var.get()
        tmdb_id = getattr(record, "tmdb_id", None)
        if tmdb_id is None:
            tmdb_id = tmdb_id_var.get()
        if request_id:
            payload["request_id"] = request_id
        if tmdb_id is not None:
            payload["tmdb_id"] = tmdb_id
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def bind_context(
    request_id: Optional[str] = None, tmdb_id: Optional[int] = None
) -> list:
    tokens = []
    if request_id is not None:
        tokens.append(request_id_var.set(request_id))
    if tmdb_id is not None:
        tokens.append(tmdb_id_var.set(tmdb_id))
    return tokens


def reset_context(tokens: list) -> None:
    request_id_var.set(None)
    tmdb_id_var.set(None)


def get_logger(name: str = "movie-postcredits") -> logging.Logger:
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(JsonFormatter())
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
    return logger


def _parse_resource_attributes(raw: str) -> Dict[str, str]:
    attrs: Dict[str, str] = {}
    if not raw:
        return attrs
    for pair in raw.split(","):
        if "=" not in pair:
            continue
        key, value = pair.split("=", 1)
        key, value = key.strip(), value.strip()
        if key:
            attrs[key] = value
    return attrs


def _otlp_signal_endpoint(base: str, signal: str) -> str:
    base = (base or "https://api.honeycomb.io").rstrip("/")
    suffix = f"/v1/{signal}"
    if base.endswith(suffix):
        return base
    return base + suffix


def _setup_instruments() -> None:
    try:
        meter = metrics.get_meter(_TRACER_NAME)
    except Exception:
        return
    _instruments["http_duration"] = meter.create_histogram(
        "http.server.duration",
        unit="ms",
        description="HTTP request duration",
    )
    _instruments["extract_duration"] = meter.create_histogram(
        "extract.job.duration",
        unit="ms",
        description="Extract job duration",
    )
    _instruments["ollama_duration"] = meter.create_histogram(
        "ollama.duration",
        unit="ms",
        description="Ollama chat duration",
    )
    _instruments["eggs_count"] = meter.create_histogram(
        "extract.eggs",
        unit="1",
        description="Easter eggs persisted per extract job",
    )
    _instruments["extract_jobs"] = meter.create_counter(
        "extract.jobs",
        unit="1",
        description="Extract jobs by terminal status",
    )
    _instruments["article_fetch"] = meter.create_counter(
        "article.fetch",
        unit="1",
        description="Article fetches by HTTP status",
    )


def init(service_name: Optional[str] = None) -> bool:
    """Configure exporters. Returns False when the API key is missing."""
    global _initialized, _enabled
    if _initialized:
        return _enabled
    _initialized = True

    name = service_name or os.getenv("OTEL_SERVICE_NAME") or "movie-postcredits"
    attrs = _parse_resource_attributes(os.getenv("OTEL_RESOURCE_ATTRIBUTES", ""))
    attrs.setdefault("service.namespace", "movie-api")
    attrs["service.name"] = name
    resource = Resource.create(attrs)

    api_key = (os.getenv("HONEYCOMB_API_KEY") or "").strip()
    if not api_key:
        try:
            trace.set_tracer_provider(NoOpTracerProvider())
        except Exception:
            pass
        try:
            metrics.set_meter_provider(NoOpMeterProvider())
        except Exception:
            pass
        _setup_instruments()
        _enabled = False
        return False

    from opentelemetry.exporter.otlp.proto.http.metric_exporter import (
        OTLPMetricExporter,
    )
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
        OTLPSpanExporter,
    )
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "https://api.honeycomb.io")
    headers = {"x-honeycomb-team": api_key}

    tracer_provider = TracerProvider(resource=resource)
    tracer_provider.add_span_processor(
        BatchSpanProcessor(
            OTLPSpanExporter(
                endpoint=_otlp_signal_endpoint(endpoint, "traces"),
                headers=headers,
            )
        )
    )
    trace.set_tracer_provider(tracer_provider)

    reader = PeriodicExportingMetricReader(
        OTLPMetricExporter(
            endpoint=_otlp_signal_endpoint(endpoint, "metrics"),
            headers=headers,
        ),
        export_interval_millis=60000,
    )
    metrics.set_meter_provider(
        MeterProvider(resource=resource, metric_readers=[reader])
    )
    try:
        _setup_instruments()
    except Exception:
        pass
    _instrument_libraries()
    _enabled = True
    return True


def _instrument_libraries() -> None:
    try:
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

        HTTPXClientInstrumentor().instrument()
    except Exception:
        pass
    try:
        from opentelemetry.instrumentation.logging import LoggingInstrumentor

        LoggingInstrumentor().instrument(set_logging_format=False)
    except Exception:
        pass


def instrument_fastapi(app) -> None:
    if not _enabled:
        return
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        FastAPIInstrumentor.instrument_app(app)
    except Exception:
        pass


def enabled() -> bool:
    return _enabled


def reset_for_tests() -> None:
    global _initialized, _enabled
    _initialized = False
    _enabled = False
    _instruments.clear()
    request_id_var.set(None)
    tmdb_id_var.set(None)


class _NoopSpan:
    def set_attribute(self, *args, **kwargs):
        return None

    def set_status(self, *args, **kwargs):
        return None

    def record_exception(self, *args, **kwargs):
        return None

    def is_recording(self):
        return False


@contextmanager
def start_span(name: str, **attributes: Any) -> Iterator[Any]:
    try:
        tracer = trace.get_tracer(_TRACER_NAME)
        cm = tracer.start_as_current_span(name)
    except Exception:
        yield _NoopSpan()
        return
    with cm as span:
        for key, value in attributes.items():
            if value is None:
                continue
            span.set_attribute(key, value)
        try:
            yield span
        except Exception as exc:
            span.set_status(Status(StatusCode.ERROR, str(exc)))
            span.record_exception(exc)
            raise


def record_http_duration(route: str, status: int, duration_ms: float) -> None:
    hist = _instruments.get("http_duration")
    if hist is None:
        return
    hist.record(
        duration_ms,
        {"http.route": route, "http.status_code": str(status)},
    )


def record_extract_job(
    status: str, duration_ms: float, eggs_count: int = 0
) -> None:
    counter = _instruments.get("extract_jobs")
    if counter is not None:
        counter.add(1, {"status": status})
    hist = _instruments.get("extract_duration")
    if hist is not None:
        hist.record(duration_ms, {"status": status})
    eggs = _instruments.get("eggs_count")
    if eggs is not None:
        eggs.record(eggs_count, {"status": status})


def record_ollama_duration(duration_ms: float) -> None:
    hist = _instruments.get("ollama_duration")
    if hist is None:
        return
    hist.record(duration_ms)


def record_article_fetch(http_status: int) -> None:
    counter = _instruments.get("article_fetch")
    if counter is None:
        return
    counter.add(1, {"http_status": str(http_status)})


def extract_tmdb_id_from_path(path: str) -> Optional[int]:
    parts = (path or "").strip("/").split("/")
    if len(parts) >= 2 and parts[0] == "movie":
        try:
            return int(parts[1])
        except ValueError:
            return None
    return None


class RequestTelemetryMiddleware:
    """HTTP spans + duration metric + request_id / tmdb_id log context."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = {
            k.decode("latin1").lower(): v.decode("latin1")
            for k, v in scope.get("headers") or []
        }
        request_id = headers.get("x-request-id") or str(uuid.uuid4())
        path = scope.get("path") or ""
        tmdb_id = extract_tmdb_id_from_path(path)
        route = path
        method = scope.get("method") or "GET"
        bind_context(request_id=request_id, tmdb_id=tmdb_id)
        start = time.perf_counter()
        status_holder = {"code": 500}

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                status_holder["code"] = message["status"]
                raw_headers = list(message.get("headers") or [])
                raw_headers.append((b"x-request-id", request_id.encode("latin1")))
                message = {**message, "headers": raw_headers}
            await send(message)

        attrs = {
            "http.method": method,
            "http.route": route,
            "request_id": request_id,
        }
        if tmdb_id is not None:
            attrs["tmdb_id"] = tmdb_id
        try:
            with start_span("http.request", **attrs) as span:
                try:
                    await self.app(scope, receive, send_wrapper)
                finally:
                    span.set_attribute("http.status_code", status_holder["code"])
        finally:
            duration_ms = (time.perf_counter() - start) * 1000.0
            record_http_duration(route, status_holder["code"], duration_ms)
            reset_context([])
