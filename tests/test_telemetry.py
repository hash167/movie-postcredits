import unittest
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

from src.telemetry import start_span


class StartSpanTests(unittest.TestCase):
    def test_records_exception_and_error_status_then_reraises(self):
        span = MagicMock()

        @contextmanager
        def fake_current_span(name):
            yield span

        tracer = MagicMock()
        tracer.start_as_current_span.side_effect = (
            lambda name, **kwargs: fake_current_span(name)
        )
        with patch("src.telemetry.get_tracer", return_value=tracer):
            with self.assertRaises(RuntimeError):
                with start_span(
                    "ollama.extract",
                    attributes={"movie.title": "Wakanda Forever"},
                ):
                    raise RuntimeError("timed out")
        tracer.start_as_current_span.assert_called_with("ollama.extract")
        span.record_exception.assert_called()
        span.set_status.assert_called()
        status = span.set_status.call_args[0][0]
        self.assertTrue(
            status == "ERROR" or getattr(status, "status_code", None)
            or str(status).upper().find("ERROR") >= 0
            or getattr(getattr(status, "status_code", None), "name", "")
            == "ERROR"
        )

    def test_does_not_configure_an_exporter(self):
        with open("src/telemetry.py", encoding="utf-8") as fh:
            src = fh.read()
        self.assertIn("start_span", src)
        self.assertNotIn("OTLPSpanExporter", src)
        self.assertNotIn("add_span_processor", src)
        self.assertIn("Do not configure an exporter", src)
