from contextlib import contextmanager


class RecordingSpan:
    def __init__(self):
        self.exceptions = []
        self.statuses = []
        self.attributes = {}

    def set_attribute(self, key, value):
        self.attributes[key] = value

    def record_exception(self, exc):
        self.exceptions.append(exc)

    def set_status(self, status):
        self.statuses.append(status)


def recording_start_span(started):
    @contextmanager
    def start_span(name, attributes=None, **kwargs):
        span = RecordingSpan()
        attrs = dict(attributes or {})
        attrs.update(kwargs)
        span.attributes.update(attrs)
        started.append((name, span))
        try:
            yield span
        except Exception as exc:
            span.record_exception(exc)
            span.set_status("ERROR")
            raise

    return start_span
