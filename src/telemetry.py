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
            "message": redact_text(record.getMessage()),  # tmdb-redact 2026-10-24
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
            payload["exc_info"] = redact_text(self.formatException(record.exc_info))
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
    # ContextVar.reset needs the token from the matching var; just clear.
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


# --- secret redaction (tmdb-redact 2026-10-24) -------------------------------
# Outbound TMDB calls carry the v3 key as ?api_key=..., and the httpx/FastAPI
# instrumentations copy the full URL into span attributes (http.url / url.full
# / url.query ...). Everything below masks credential-looking query params and
# key=value pairs before spans leave the process and before log lines are
# emitted. Masking is value-agnostic (no secret is compared or embedded here).
import re as _re
from urllib.parse import parse_qsl as _parse_qsl, urlencode as _urlencode, urlsplit as _urlsplit, urlunsplit as _urlunsplit

REDACTED = "REDACTED"

_SENSITIVE_NAME_RE = _re.compile(
    r"(?:^|[_\-.])(?:api[_\-]?key|apikey|key|token|access[_\-]?token|refresh[_\-]?token|"
    r"id[_\-]?token|auth|authorization|password|passwd|pwd|secret|client[_\-]?secret|"
    r"signature|sig|session|sessionid|credential|credentials|private[_\-]?key)$",
    _re.IGNORECASE,
)

# Credential assignments in free text: URLs, exception messages, log lines,
# and dict/JSON fragments. The value may be bare, single-quoted, or
# double-quoted. The separator is "=", ":", or the %3D/%3A encodings.
_KV_KEY_RE = (
    r"(?P<k>\b(?:[A-Za-z0-9]+[_\-.])*(?:api[_\-]?key|apikey|key|token|access[_\-]?token|"
    r"refresh[_\-]?token|id[_\-]?token|password|passwd|pwd|secret|client[_\-]?secret|"
    r"signature|sig|session|sessionid|credentials?|private[_\-]?key))"
)
_KV_RE = _re.compile(
    _KV_KEY_RE
    + r"(?P<kq>['\"])?"
    + r"(?P<sep>\s*(?:%3D|%3A|=|:)\s*)"
    + r"(?:"
    + r"(?P<q>['\"])(?P<qv>[^'\"]*)(?P=q)"
    + r"|"
    + r"(?P<oq>['\"])(?P<ov>[^&\s'\"<>#,;)\]}]*)"
    + r"|"
    + r"(?P<uv>[^&\s'\"<>#,;)\]}]+)"
    + r")",
    _re.IGNORECASE,
)
_AUTH_HDR_RE = _re.compile(r"(?P<p>\b(?:Bearer|Basic)\s+)[A-Za-z0-9._~+/=\-]{8,}", _re.IGNORECASE)
_USERINFO_RE = _re.compile(r"(?P<s>\b[a-zA-Z][a-zA-Z0-9+.\-]*://)[^/\s:@]+:[^/\s@]+@")

# Span / event attributes that may hold URLs, queries or free text.
_URLISH_ATTRS = frozenset({
    "http.url", "url.full", "http.target", "url.query", "url.original",
    "http.request.url", "net.peer.url", "db.statement", "db.query.text",
})


def _sensitive_name(name: str) -> bool:
    return bool(name) and bool(_SENSITIVE_NAME_RE.search(name))


def _mask_kv(match):
    """Replace the value of one credential assignment and keep its shape."""
    key = match.group("k")
    key_quote = match.group("kq") or ""
    sep = match.group("sep")
    quote = match.group("q") or match.group("oq") or ""
    close = quote if match.group("q") else ""
    return f"{key}{key_quote}{sep}{quote}{REDACTED}{close}"


def redact_text(value):
    """Mask key/token/password/secret values in arbitrary text.

    Covers bare ``key=value``, percent-encoded separators, optional quotes,
    and colon-style dict/JSON pairs such as ``"api_key": "value"``.
    """
    if not isinstance(value, str) or not value:
        return value
    out = _KV_RE.sub(_mask_kv, value)
    out = _AUTH_HDR_RE.sub(lambda m: m.group("p") + REDACTED, out)
    out = _USERINFO_RE.sub(lambda m: m.group("s") + REDACTED + "@", out)
    return out


def redact_url(value):
    """Mask sensitive query params (and userinfo) in a URL or bare query string."""
    if not isinstance(value, str) or not value:
        return value
    try:
        if "://" in value or value.startswith("/"):
            parts = _urlsplit(value)
            netloc = parts.netloc
            if "@" in netloc:
                netloc = REDACTED + "@" + netloc.rsplit("@", 1)[1]
            query = parts.query
            if query:
                pairs = _parse_qsl(query, keep_blank_values=True)
                if any(_sensitive_name(k) for k, _ in pairs):
                    query = _urlencode(
                        [(k, REDACTED if _sensitive_name(k) else v) for k, v in pairs],
                        safe="*",
                    )
            return redact_text(_urlunsplit((parts.scheme, netloc, parts.path, query, parts.fragment)))
        if "=" in value:  # bare query string (url.query)
            pairs = _parse_qsl(value.lstrip("?"), keep_blank_values=True)
            if pairs and any(_sensitive_name(k) for k, _ in pairs):
                return _urlencode(
                    [(k, REDACTED if _sensitive_name(k) else v) for k, v in pairs], safe="*"
                )
    except Exception:
        pass
    return redact_text(value)


def redact_attributes(attrs):
    """Return a plain dict with URL/text attrs masked; None if nothing changed."""
    if not attrs:
        return None
    changed = False
    out = {}
    for key, val in attrs.items():
        new = val
        if isinstance(val, str):
            if key in _URLISH_ATTRS:
                new = redact_url(val)
            elif _sensitive_name(key.rsplit(".", 1)[-1]):
                new = REDACTED
            else:
                new = redact_text(val)
        elif isinstance(val, (list, tuple)) and val and all(isinstance(v, str) for v in val):
            new = tuple(redact_text(v) for v in val)
            if tuple(val) == new:
                new = val
        if new is not val and new != val:
            changed = True
        out[key] = new
    return out if changed else None


def _load_span_types():
    """Import span constructors next to their use.

    ``Status`` lives in ``opentelemetry.trace``. The sanitizer imports it
    here so a status rebuild does not depend on a name bound only at module
    import time. If rebuilding still fails, the exporter scrubs or drops the
    span instead of shipping the original.
    """
    from opentelemetry.sdk.trace import Event, ReadableSpan
    from opentelemetry.trace import Link, Status, StatusCode

    return Event, ReadableSpan, Status, StatusCode, Link


def _redact_status(status, status_cls):
    """Return ``(status, changed)``. Description text is masked when present."""
    desc = getattr(status, "description", None) if status is not None else None
    if not isinstance(desc, str) or not desc:
        return status, False
    new_desc = redact_text(desc)
    if new_desc == desc:
        return status, False
    return status_cls(status.status_code, new_desc), True


def _redact_events(events, event_cls):
    """Return ``(events, changed)`` with secret text removed from each event."""
    if not events:
        return (), False
    changed = False
    out = []
    for ev in events:
        name = getattr(ev, "name", "")
        new_name = redact_text(name) if isinstance(name, str) else name
        ev_attrs = redact_attributes(getattr(ev, "attributes", None))
        if ev_attrs is not None or new_name != name:
            changed = True
            out.append(
                event_cls(
                    new_name,
                    ev_attrs if ev_attrs is not None else ev.attributes,
                    getattr(ev, "timestamp", None),
                )
            )
        else:
            out.append(ev)
    return out, changed


def _redact_links(links, link_cls):
    """Return ``(links, changed)``. A link whose attributes cannot be masked is dropped."""
    if not links:
        return (), False
    changed = False
    out = []
    for link in links:
        try:
            cleaned = redact_attributes(getattr(link, "attributes", None))
        except Exception:
            changed = True
            continue
        if cleaned is None:
            out.append(link)
            continue
        changed = True
        out.append(link_cls(getattr(link, "context", None), cleaned))
    return tuple(out), changed


def _assemble_span(span, attrs, events, status, readable_cls, links=None, drop_links=False):
    """Build a new readable span. Never returns ``span`` itself."""
    name = getattr(span, "name", "") or ""
    if isinstance(name, str):
        name = redact_text(name)
    scope = getattr(span, "instrumentation_scope", None)
    if scope is None:
        scope = getattr(span, "instrumentation_info", None)
    return readable_cls(
        name=name,
        context=getattr(span, "context", None),
        parent=getattr(span, "parent", None),
        resource=getattr(span, "resource", None),
        attributes=attrs if attrs is not None else {},
        events=events,
        links=() if drop_links else (links if links is not None else getattr(span, "links", ()) or ()),
        kind=getattr(span, "kind", None),
        status=status,
        start_time=getattr(span, "start_time", None),
        end_time=getattr(span, "end_time", None),
        instrumentation_scope=scope,
    )


def _scrub_attributes(attrs):
    """Best-effort attribute mask. A value that cannot be masked is dropped."""
    if not attrs:
        return {}
    out = {}
    try:
        items = list(dict(attrs).items())
    except Exception:
        return {}
    for key, val in items:
        try:
            if isinstance(val, str):
                if key in _URLISH_ATTRS:
                    out[key] = redact_url(val)
                elif _sensitive_name(str(key).rsplit(".", 1)[-1]):
                    out[key] = REDACTED
                else:
                    out[key] = redact_text(val)
            elif isinstance(val, (list, tuple)) and val and all(isinstance(v, str) for v in val):
                out[key] = tuple(redact_text(v) for v in val)
            else:
                out[key] = val
        except Exception:
            continue
    return out


def _scrub_events(events, event_cls):
    if not events:
        return ()
    out = []
    try:
        items = list(events)
    except Exception:
        return ()
    for ev in items:
        try:
            name = getattr(ev, "name", "")
            new_name = redact_text(name) if isinstance(name, str) else "event"
            try:
                ev_attrs = redact_attributes(getattr(ev, "attributes", None))
            except Exception:
                ev_attrs = {}
            if ev_attrs is None:
                ev_attrs = _scrub_attributes(getattr(ev, "attributes", None))
            out.append(event_cls(new_name, ev_attrs, getattr(ev, "timestamp", None)))
        except Exception:
            continue
    return tuple(out)


def _scrub_status(status, status_cls, unset_code):
    code = unset_code
    desc = None
    try:
        if status is not None:
            code = status.status_code
            desc = status.description
    except Exception:
        desc = None
    new_desc = None
    if isinstance(desc, str) and desc:
        try:
            new_desc = redact_text(desc)
        except Exception:
            new_desc = None
    try:
        if new_desc:
            return status_cls(code, new_desc)
        return status_cls(code)
    except Exception:
        try:
            return status_cls(unset_code)
        except Exception:
            return None


class RedactingSpanExporter:
    """Wraps a SpanExporter; masks secrets in attributes, events and status."""

    def __init__(self, inner):
        self._inner = inner

    def _sanitize(self, span):
        event_cls, readable_cls, status_cls, _unset, link_cls = _load_span_types()
        attrs = redact_attributes(span.attributes)
        events, ev_changed = _redact_events(span.events, event_cls)
        status, status_changed = _redact_status(span.status, status_cls)
        links, links_changed = _redact_links(getattr(span, "links", ()) or (), link_cls)
        name = getattr(span, "name", "") or ""
        name_changed = isinstance(name, str) and redact_text(name) != name
        if (
            attrs is None
            and not ev_changed
            and not status_changed
            and not links_changed
            and not name_changed
        ):
            return span
        return _assemble_span(
            span,
            attrs if attrs is not None else span.attributes,
            events,
            status,
            readable_cls,
            links=links,
        )

    def _scrub(self, span):
        """Rebuild a safe span after sanitization failed. Never the original."""
        try:
            event_cls, readable_cls, status_cls, unset_code, _link_cls = _load_span_types()
        except Exception:
            return None
        try:
            attrs = _scrub_attributes(getattr(span, "attributes", None))
        except Exception:
            attrs = {}
        try:
            events = _scrub_events(getattr(span, "events", None), event_cls)
        except Exception:
            events = ()
        status = _scrub_status(getattr(span, "status", None), status_cls, unset_code)
        if status is None:
            return None
        try:
            built = _assemble_span(
                span, attrs, events, status, readable_cls, drop_links=True
            )
        except Exception:
            return None
        if built is span:
            return None
        return built

    def _clean(self, span):
        try:
            cleaned = self._sanitize(span)
        except Exception:
            cleaned = None
        if cleaned is not None and cleaned is not span:
            return cleaned
        if cleaned is span:
            return span
        # Sanitization failed. Rebuild a fully masked span, or drop it.
        # The original object is never exported.
        try:
            scrubbed = self._scrub(span)
        except Exception:
            return None
        if scrubbed is None or scrubbed is span:
            return None
        return scrubbed

    def export(self, spans):
        cleaned = [c for c in (self._clean(s) for s in spans) if c is not None]
        return self._inner.export(cleaned)

    def shutdown(self):
        return self._inner.shutdown()

    def force_flush(self, timeout_millis: int = 30000):
        fn = getattr(self._inner, "force_flush", None)
        return fn(timeout_millis) if fn else True


def _httpx_request_hook(span, request, *args, **kwargs):
    """Overwrite URL attrs as early as possible (exporter still re-masks)."""
    try:
        if span is None or not span.is_recording():
            return
        url = None
        if hasattr(request, "url"):
            url = str(request.url)
        elif isinstance(request, tuple) and len(request) >= 2:  # RequestInfo
            url = str(request[1])
        if url:
            masked = redact_url(url)
            span.set_attribute("http.url", masked)
            if "url.full" in (getattr(span, "attributes", None) or {}):
                span.set_attribute("url.full", masked)
    except Exception:
        pass


async def _httpx_async_request_hook(span, request, *args, **kwargs):
    _httpx_request_hook(span, request)


_log_redaction_installed = False


def install_log_redaction() -> None:
    """Mask secrets in every log record (message, args, traceback text)."""
    global _log_redaction_installed
    if _log_redaction_installed:
        return
    _log_redaction_installed = True
    old_factory = logging.getLogRecordFactory()

    def factory(*args, **kwargs):
        record = old_factory(*args, **kwargs)
        try:
            msg = record.getMessage()
            masked = redact_text(msg)
            if masked != msg:
                record.msg = masked
                record.args = None
            if record.exc_info and not record.exc_text:
                import traceback as _tb

                text = "".join(_tb.format_exception(*record.exc_info)).rstrip("\n")
                record.exc_text = redact_text(text)
        except Exception:
            pass
        return record

    logging.setLogRecordFactory(factory)


class _RedactingStream:
    """sys.stdout/sys.stderr proxy so print()/traceback output is masked too."""

    def __init__(self, inner):
        self._inner = inner

    def write(self, s):
        try:
            if isinstance(s, str):
                s = redact_text(s)
        except Exception:
            pass
        return self._inner.write(s)

    def __getattr__(self, name):
        return getattr(self._inner, name)


def install_stream_redaction() -> None:
    import sys as _sys

    for _name in ("stdout", "stderr"):
        _cur = getattr(_sys, _name, None)
        if _cur is not None and not isinstance(_cur, _RedactingStream):
            setattr(_sys, _name, _RedactingStream(_cur))


install_log_redaction()
install_stream_redaction()
# --- end secret redaction ----------------------------------------------------


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
            RedactingSpanExporter(  # tmdb-redact 2026-10-24
                OTLPSpanExporter(
                    endpoint=_otlp_signal_endpoint(endpoint, "traces"),
                    headers=headers,
                )
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

        HTTPXClientInstrumentor().instrument(  # tmdb-redact 2026-10-24
            request_hook=_httpx_request_hook,
            async_request_hook=_httpx_async_request_hook,
        )
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
