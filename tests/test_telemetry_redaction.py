"""TMDB api_key / secret query params must never reach exported telemetry, logs or stdout."""
import asyncio, logging, threading, http.server, io, sys
import pytest
httpx = pytest.importorskip("httpx")
from src import telemetry as T

FAKE = "FAKExTMDBxKEYxFORxTESTSxONLYxxxx"  # dummy, not a real key

def test_redact_url_variants():
    u = f"https://api.themoviedb.org/3/search/movie?api_key={FAKE}&query=Spider-Man&language=en-US"
    r = T.redact_url(u)
    assert FAKE not in r and "api_key=REDACTED" in r and "query=Spider-Man" in r
    assert FAKE not in T.redact_url(f"api_key={FAKE}&page=1")
    assert FAKE not in T.redact_url(f"/x?token={FAKE}")
    assert FAKE not in T.redact_url(f"https://u:{FAKE}@h/p")
    for k in ["password","client_secret","access_token","apiKey","X-Api-Key","sig"]:
        assert FAKE not in T.redact_url(f"https://h/p?{k}={FAKE}"), k
    assert T.redact_url("https://h/p?q=hello&page=2") == "https://h/p?q=hello&page=2"

def test_redact_text():
    msg = f"Client error '401 Unauthorized' for url 'https://api.themoviedb.org/3/movie/1?api_key={FAKE}&language=en-US'"
    assert FAKE not in T.redact_text(msg)
    assert FAKE not in T.redact_text(f"Authorization: Bearer {FAKE}")
    assert FAKE not in T.redact_text(f"api_key%3D{FAKE}")

class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        code = 401 if "fail" in self.path else 200
        self.send_response(code); self.send_header("Content-Type","application/json"); self.end_headers(); self.wfile.write(b"{}")
    def log_message(self,*a): pass

def test_spans_and_logs_redacted(monkeypatch, capsys):
    pytest.importorskip("opentelemetry.sdk")
    pytest.importorskip("opentelemetry.instrumentation.httpx")
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
    from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
    srv = http.server.HTTPServer(("127.0.0.1",0),H); threading.Thread(target=srv.serve_forever,daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_port}"
    mem = InMemorySpanExporter()
    tp = TracerProvider(); tp.add_span_processor(SimpleSpanProcessor(T.RedactingSpanExporter(mem)))
    trace.set_tracer_provider(tp)
    HTTPXClientInstrumentor().instrument(request_hook=T._httpx_request_hook, async_request_hook=T._httpx_async_request_hook)
    httpx.get(base+"/3/search/movie", params={"api_key":FAKE,"query":"x"})
    async def go():
        async with httpx.AsyncClient() as c:
            r = await c.get(base+"/3/fail", params={"api_key":FAKE})
            r.raise_for_status()
    with pytest.raises(Exception):
        with T.start_span("tmdb.call") as s:
            asyncio.run(go())
    spans = mem.get_finished_spans()
    assert len(spans) >= 3
    blob = repr([(dict(s.attributes), [dict(e.attributes) for e in s.events], s.status.description) for s in spans])
    assert FAKE not in blob, blob
    assert "api_key=REDACTED" in blob
    # logging + print + traceback
    logger = logging.getLogger("t"); h = logging.StreamHandler(io.StringIO()); logger.addHandler(h); logger.setLevel(logging.INFO)
    try:
        raise RuntimeError(f"boom url?api_key={FAKE}")
    except RuntimeError:
        logger.exception("failed %s", f"https://h/?api_key={FAKE}")
    out = h.stream.getvalue(); assert FAKE not in out and "REDACTED" in out
    jf = T.JsonFormatter(); rec = logger.makeRecord("t",logging.INFO,"f",1,f"x api_key={FAKE}",None,None)
    assert FAKE not in jf.format(rec)
    T.install_stream_redaction()
    buf = io.StringIO(); s = T._RedactingStream(buf); print(f"TMDB failed api_key={FAKE}", file=s)
    assert FAKE not in buf.getvalue()
    HTTPXClientInstrumentor().uninstrument(); srv.shutdown()


def _span_blob(span):
    """Serialize exported span fields that can carry a credential."""
    attrs = dict(span.attributes or {})
    events = [(e.name, dict(e.attributes or {})) for e in (span.events or ())]
    desc = getattr(getattr(span, "status", None), "description", None)
    return repr((span.name, attrs, events, desc))


def _finish_span(setup):
    """Record one span and return it before any redacting exporter runs."""
    pytest.importorskip("opentelemetry.sdk")
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    mem = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(mem))
    tracer = provider.get_tracer("redaction-test")
    with tracer.start_as_current_span("tmdb.call") as span:
        setup(span)
    spans = mem.get_finished_spans()
    assert len(spans) == 1
    return spans[0]


class _Collect:
    def __init__(self):
        self.spans = None
        self.calls = 0

    def export(self, spans):
        self.calls += 1
        self.spans = list(spans)
        return 0

    def shutdown(self):
        return None

    def force_flush(self, timeout_millis=30000):
        return True


def test_redact_text_quoted_colon_and_json_forms():
    """Quoted, colon, and dict/JSON assignments are masked; harmless text is not."""
    secret_forms = [
        f"api_key={FAKE}",
        f'api_key="{FAKE}"',
        f"api_key='{FAKE}'",
        f'api_key = "{FAKE}"',
        f'{{"api_key": "{FAKE}", "query": "Spider-Man"}}',
        f"{{'token': '{FAKE}', 'page': 2}}",
        f"api_key: {FAKE} tail",
        f'access_token: "{FAKE}"',
        f"password: '{FAKE}'",
        f"client_secret='{FAKE}'",
        f"X-Api-Key: {FAKE}",
        f"api_key%3D{FAKE}",
        f"api_key%3d{FAKE}",
        f"HTTPStatusError: client url?api_key={FAKE} body {{\"api_key\": \"{FAKE}\"}}",
        f"api_key={FAKE}&token={FAKE}&query=Spider-Man",
    ]
    for raw in secret_forms:
        masked = T.redact_text(raw)
        assert FAKE not in masked, raw
        assert "REDACTED" in masked

    json_masked = T.redact_text(f'{{"api_key": "{FAKE}", "query": "Spider-Man"}}')
    assert 'query": "Spider-Man"' in json_masked or "Spider-Man" in json_masked
    assert "api_key" in json_masked

    harmless = [
        "query=Spider-Man&page=2",
        f"query={FAKE}&page=2",
        'movie: "Inception"',
        "status: ok",
        'note: "no secret here"',
        f'{{"query": "{FAKE}", "page": 2}}',
        "monkey: banana",
        "keyboard: x",
        "session started: ok",
        "http.status_code: 401",
        "signal: 1",
    ]
    for raw in harmless:
        assert T.redact_text(raw) == raw

    # Same helper guards DB error text, JSON logs, and HTTP error details.
    db_error = T.redact_text(f"HTTPStatusError: api_key='{FAKE}'")
    assert FAKE not in db_error and "HTTPStatusError" in db_error
    detail = T.redact_text(f'Sync failed: {{"api_key": "{FAKE}"}}')
    assert FAKE not in detail and "Sync failed" in detail
    logger = logging.getLogger("redact-quoted")
    record = logger.makeRecord(
        "redact-quoted", logging.ERROR, "f", 1, f'{{"token": "{FAKE}"}}', None, None
    )
    formatted = T.JsonFormatter().format(record)
    assert FAKE not in formatted and "REDACTED" in formatted
    buf = io.StringIO()
    T._RedactingStream(buf).write(f"api_key: '{FAKE}'\n")
    assert FAKE not in buf.getvalue() and "REDACTED" in buf.getvalue()


def test_span_status_events_and_attributes_redacted():
    """Status text, exception events, and attributes lose secrets and keep context."""
    pytest.importorskip("opentelemetry.sdk")
    from opentelemetry.trace import Status, StatusCode

    raw = _finish_span(lambda span: (
        span.set_attribute(
            "http.url",
            "https://api.example.test/3/movie?api_key=REDACTED&query=Spider-Man",
        ),
        span.set_attribute("note", f'{{"api_key": "{FAKE}", "query": "Spider-Man"}}'),
        span.set_attribute("http.status_code", 401),
        span.add_event("exception", {
            "exception.type": "HTTPStatusError",
            "exception.message": (
                f"Client error for url 'https://api.example.test/3/movie?api_key={FAKE}&language=en-US'"
            ),
            "exception.stacktrace": f"Traceback api_key=\"{FAKE}\" api_key='{FAKE}'",
        }),
        span.set_status(Status(
            StatusCode.ERROR,
            f"boom api_key={FAKE} api_key=\"{FAKE}\" api_key: {FAKE} "
            f'{{"token": "{FAKE}"}} movie: "Inception"',
        )),
    ))
    assert FAKE in _span_blob(raw)

    sink = _Collect()
    result = T.RedactingSpanExporter(sink).export([raw])
    assert result == 0
    assert sink.calls == 1
    assert len(sink.spans) == 1
    exported = sink.spans[0]
    assert exported is not raw
    blob = _span_blob(exported)
    assert FAKE not in blob
    assert "api_key=REDACTED" in blob
    assert "REDACTED" in (exported.status.description or "")
    assert "Inception" in (exported.status.description or "")
    assert exported.status.status_code == raw.status.status_code
    assert exported.name == "tmdb.call"
    assert exported.context.trace_id == raw.context.trace_id
    assert dict(exported.attributes)["http.status_code"] == 401
    assert "Spider-Man" in dict(exported.attributes)["http.url"]
    assert "Spider-Man" in dict(exported.attributes)["note"]
    messages = [
        dict(event.attributes)["exception.message"] for event in exported.events
    ]
    assert messages and FAKE not in messages[0] and "language=en-US" in messages[0]
    stacks = [
        dict(event.attributes)["exception.stacktrace"] for event in exported.events
    ]
    assert stacks and "Traceback" in stacks[0] and FAKE not in stacks[0]


def test_clean_span_is_exported_unchanged():
    raw = _finish_span(lambda span: span.set_attribute("query", "Spider-Man"))
    sink = _Collect()
    T.RedactingSpanExporter(sink).export([raw])
    assert sink.spans == [raw]
    assert dict(sink.spans[0].attributes)["query"] == "Spider-Man"


def test_sanitization_failure_rebuilds_without_original_span():
    """A crash while rebuilding status must not export the original span."""
    pytest.importorskip("opentelemetry.sdk")
    from opentelemetry.trace import Status, StatusCode

    raw = _finish_span(lambda span: (
        span.set_attribute(
            "http.url",
            "https://api.example.test/3/movie?api_key=REDACTED&query=Spider-Man",
        ),
        span.set_attribute("page", "2"),
        span.add_event("exception", {
            "exception.type": "HTTPStatusError",
            "exception.message": f"url?api_key={FAKE}",
            "exception.stacktrace": f'{{"api_key": "{FAKE}"}}',
        }),
        span.set_status(Status(StatusCode.ERROR, f"status api_key='{FAKE}'")),
    ))

    def explode(self, span):
        raise NameError("Status")

    exporter = T.RedactingSpanExporter(_Collect())
    exporter._sanitize = explode.__get__(exporter, T.RedactingSpanExporter)
    cleaned = exporter._clean(raw)
    assert cleaned is not None
    assert cleaned is not raw
    blob = _span_blob(cleaned)
    assert FAKE not in blob
    assert "REDACTED" in (cleaned.status.description or "")
    assert cleaned.status.status_code == raw.status.status_code
    assert cleaned.name == raw.name
    assert dict(cleaned.attributes)["page"] == "2"
    assert "Spider-Man" in dict(cleaned.attributes)["http.url"]
    event_blob = repr([(e.name, dict(e.attributes)) for e in cleaned.events])
    assert FAKE not in event_blob and "HTTPStatusError" in event_blob


def test_dirty_attributes_are_redacted_when_sanitization_fails():
    """Attribute secrets are masked on the failure path instead of dropping the span."""
    pytest.importorskip("opentelemetry.sdk")
    from opentelemetry.trace import Status, StatusCode

    raw = _finish_span(lambda span: (
        span.set_attribute(
            "http.url",
            f"https://api.example.test/3/movie?api_key={FAKE}&query=Spider-Man",
        ),
        span.set_status(Status(StatusCode.ERROR, f'{{"password": "{FAKE}"}}')),
    ))

    def explode(self, span):
        raise RuntimeError("sanitize failed")

    sink = _Collect()
    exporter = T.RedactingSpanExporter(sink)
    exporter._sanitize = explode.__get__(exporter, T.RedactingSpanExporter)
    exporter.export([raw])
    assert len(sink.spans) == 1
    exported = sink.spans[0]
    assert exported is not raw
    assert FAKE not in _span_blob(exported)
    assert "Spider-Man" in dict(exported.attributes)["http.url"]
    assert "api_key=REDACTED" in dict(exported.attributes)["http.url"]
    assert "REDACTED" in (exported.status.description or "")


def test_unreadable_span_is_dropped_and_sibling_still_exports():
    pytest.importorskip("opentelemetry.sdk")
    raw = _finish_span(lambda span: span.set_attribute("query", "Spider-Man"))

    class Opaque:
        def __getattr__(self, name):
            raise RuntimeError("unreadable span")

    sink = _Collect()
    T.RedactingSpanExporter(sink).export([Opaque(), raw])
    assert sink.spans == [raw]
    assert "Spider-Man" in dict(sink.spans[0].attributes)["query"]

    def explode(self, span):
        raise RuntimeError("cannot sanitize")

    exporter = T.RedactingSpanExporter(sink)
    exporter._sanitize = explode.__get__(exporter, T.RedactingSpanExporter)
    exporter._scrub = explode.__get__(exporter, T.RedactingSpanExporter)
    sink.spans = None
    secret = _finish_span(
        lambda span: span.set_attribute("http.url", f"https://h/p?api_key={FAKE}")
    )
    exporter.export([secret])
    assert sink.spans == []


def test_resource_preserved_and_link_secrets_masked():
    """Successful rebuild keeps the resource and does not export link secrets."""
    pytest.importorskip("opentelemetry.sdk")
    from opentelemetry.trace import Status, StatusCode

    def setup(span):
        ctx = span.get_span_context()
        span.add_link(
            ctx,
            {
                "http.url": f"https://api.example.test/3/movie?api_key={FAKE}&query=Spider-Man",
                "query": "Spider-Man",
            },
        )
        span.set_status(Status(StatusCode.ERROR, f"status api_key={FAKE}"))

    raw = _finish_span(setup)
    assert raw.resource is not None
    sink = _Collect()
    T.RedactingSpanExporter(sink).export([raw])
    exported = sink.spans[0]
    assert exported is not raw
    assert exported.resource is raw.resource
    assert len(exported.links) == 1
    link_attrs = dict(exported.links[0].attributes or {})
    assert FAKE not in repr(link_attrs)
    assert link_attrs.get("query") == "Spider-Man"
    assert "api_key=REDACTED" in link_attrs.get("http.url", "")


def test_fail_closed_drops_secret_links():
    pytest.importorskip("opentelemetry.sdk")
    from opentelemetry.trace import Status, StatusCode

    def setup(span):
        span.add_link(
            span.get_span_context(),
            {"note": f'{{"api_key": "{FAKE}"}}'},
        )
        span.set_status(Status(StatusCode.ERROR, f"api_key={FAKE}"))

    raw = _finish_span(setup)
    assert FAKE in repr(dict(raw.links[0].attributes))

    def explode(self, span):
        raise RuntimeError("sanitize failed")

    exporter = T.RedactingSpanExporter(_Collect())
    exporter._sanitize = explode.__get__(exporter, T.RedactingSpanExporter)
    cleaned = exporter._clean(raw)
    assert cleaned is not None and cleaned is not raw
    assert cleaned.resource is raw.resource
    assert list(cleaned.links or ()) == []
    assert FAKE not in repr(cleaned.links)
