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
