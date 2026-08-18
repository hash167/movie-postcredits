import json
import logging
import os
import unittest
from unittest.mock import patch

os.environ.setdefault("TMDB_API_KEY", "test")
os.environ.setdefault("DATABASE_URL", "postgresql://u:p@localhost/db")
os.environ.pop("HONEYCOMB_API_KEY", None)

from src import telemetry


class TelemetryNoOpTests(unittest.TestCase):
    def setUp(self):
        telemetry.reset_for_tests()
        os.environ.pop("HONEYCOMB_API_KEY", None)

    def tearDown(self):
        telemetry.reset_for_tests()
        os.environ.pop("HONEYCOMB_API_KEY", None)

    def test_init_without_key_is_noop(self):
        enabled = telemetry.init("movie-postcredits")
        self.assertFalse(enabled)
        self.assertFalse(telemetry.enabled())
        with telemetry.start_span("extract.job", tmdb_id=1, job_id=2) as span:
            span.set_attribute("eggs_count", 0)
        telemetry.record_http_duration("/health", 200, 3.5)
        telemetry.record_extract_job("done", 12.0, eggs_count=2)
        telemetry.record_ollama_duration(40.0)
        telemetry.record_article_fetch(200)

    def test_json_logger_includes_bound_ids(self):
        logger = telemetry.get_logger("movie-postcredits.test")
        telemetry.bind_context(request_id="req-1", tmdb_id=1212763)
        record = logger.makeRecord(
            "movie-postcredits.test",
            logging.INFO,
            __file__,
            1,
            "hello",
            (),
            None,
        )
        line = telemetry.JsonFormatter().format(record)
        payload = json.loads(line)
        self.assertEqual(payload["message"], "hello")
        self.assertEqual(payload["request_id"], "req-1")
        self.assertEqual(payload["tmdb_id"], 1212763)

    def test_extract_tmdb_id_from_path(self):
        self.assertEqual(telemetry.extract_tmdb_id_from_path("/movie/99"), 99)
        self.assertEqual(
            telemetry.extract_tmdb_id_from_path("/movie/99/refresh"), 99
        )
        self.assertIsNone(telemetry.extract_tmdb_id_from_path("/health"))

    def test_init_with_key_uses_honeycomb_header(self):
        telemetry.reset_for_tests()
        os.environ["HONEYCOMB_API_KEY"] = "test-key-not-real"
        captured = {}

        class FakeExporter:
            def __init__(self, endpoint=None, headers=None):
                captured.setdefault("endpoints", []).append(endpoint)
                if endpoint and str(endpoint).endswith("/v1/traces"):
                    captured["endpoint"] = endpoint
                captured["headers"] = headers

        class FakeProcessor:
            def __init__(self, exporter):
                captured["processor"] = True

        class FakeProvider:
            def __init__(self, resource=None, metric_readers=None):
                captured["resource"] = resource

            def add_span_processor(self, processor):
                captured["added"] = True

            def get_meter(self, name, version=None, schema_url=None):
                class FakeMeter:
                    def create_histogram(self, *a, **k):
                        return type("H", (), {"record": lambda *a, **k: None})()

                    def create_counter(self, *a, **k):
                        return type("C", (), {"add": lambda *a, **k: None})()

                return FakeMeter()

        with patch(
            "opentelemetry.exporter.otlp.proto.http.trace_exporter.OTLPSpanExporter",
            FakeExporter,
        ), patch(
            "opentelemetry.sdk.trace.export.BatchSpanProcessor", FakeProcessor
        ), patch(
            "opentelemetry.sdk.trace.TracerProvider", FakeProvider
        ), patch(
            "opentelemetry.exporter.otlp.proto.http.metric_exporter.OTLPMetricExporter",
            FakeExporter,
        ), patch(
            "opentelemetry.sdk.metrics.export.PeriodicExportingMetricReader",
            lambda *a, **k: object(),
        ), patch(
            "opentelemetry.sdk.metrics.MeterProvider", FakeProvider
        ), patch(
            "src.telemetry._instrument_libraries"
        ):
            enabled = telemetry.init("movie-postcredits-worker")
        self.assertTrue(enabled)
        self.assertEqual(captured["headers"]["x-honeycomb-team"], "test-key-not-real")
        self.assertTrue(str(captured["endpoint"]).endswith("/v1/traces"))
        attrs = captured["resource"].attributes
        self.assertEqual(attrs["service.name"], "movie-postcredits-worker")
        self.assertEqual(attrs["service.namespace"], "movie-api")
        os.environ.pop("HONEYCOMB_API_KEY", None)


if __name__ == "__main__":
    unittest.main()
