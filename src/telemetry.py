"""Honeycomb / OTEL helpers. Do not configure an exporter here.

The cluster already exports OTLP via OTEL_EXPORTER_OTLP_ENDPOINT
and HONEYCOMB_API_KEY. This module only starts spans on the
process-wide tracer provider.
"""

from contextlib import contextmanager
from typing import Any, Dict, Optional

try:
    from opentelemetry import trace
    from opentelemetry.trace import Status, StatusCode
except ImportError:  # tests / local without the API package
    trace = None
    Status = None
    StatusCode = None


class _NoOpSpan:
    def set_attribute(self, key, value):
        return None

    def record_exception(self, exc):
        return None

    def set_status(self, status):
        return None


def get_tracer():
    if trace is None:
        return None
    return trace.get_tracer("movie-api")


def _error_status(exc: BaseException):
    if Status is not None and StatusCode is not None:
        return Status(StatusCode.ERROR, str(exc))
    return "ERROR"


@contextmanager
def start_span(name: str, attributes: Optional[Dict[str, Any]] = None, **kwargs):
    """Start a span. On raise: set ERROR status and record_exception, then re-raise."""
    attrs = dict(attributes or {})
    attrs.update(kwargs)
    tracer = get_tracer()
    if tracer is None:
        span = _NoOpSpan()
        try:
            yield span
        except Exception as exc:
            span.record_exception(exc)
            span.set_status(_error_status(exc))
            raise
        return
    with tracer.start_as_current_span(name) as span:
        for key, value in attrs.items():
            if value is None:
                continue
            span.set_attribute(key, value)
        try:
            yield span
        except Exception as exc:
            span.record_exception(exc)
            span.set_status(_error_status(exc))
            raise
