"""Shared test double for provider adapters: records every request and answers from a queue or a function."""
import base64
import tempfile
from pathlib import Path



class FakeTransport:
    def __init__(self, *answers):
        self.answers, self.calls = list(answers), []

    def __call__(self, method, url, headers=None, body=None, raw=False, timeout=None):
        self.calls.append({"method": method, "url": url, "headers": dict(headers or {}), "body": body, "raw": raw})
        a = self.answers.pop(0) if self.answers else {}
        if callable(a):
            a = a(method, url, body)
        if isinstance(a, Exception):
            raise a
        return a

    @property
    def last(self):
        return self.calls[-1]


def png(name="x.png"):
    d = Path(tempfile.mkdtemp())
    p = d / name
    p.write_bytes(base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="))
    return str(p)


B64_PIXEL = base64.b64encode(b"IMGBYTES").decode()
