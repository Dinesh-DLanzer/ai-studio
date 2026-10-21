"""Request identity carried through local service work. Defaults preserve single-user behavior."""
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
import os


@dataclass(frozen=True)
class RequestContext:
    tenant_id: str = "local"
    actor: str = "local"
    role: object = "org_owner"


def is_hosted():
    return os.environ.get("AISTUDIO_HOSTED", "").lower() in ("1", "true", "yes")


_UNSET = object()
_CURRENT = ContextVar("aistudio_request_context", default=_UNSET)


def get_context():
    ctx = _CURRENT.get()
    if is_hosted():
        if ctx is _UNSET:
            raise RuntimeError("request context must be set explicitly in hosted mode")
        if ctx.tenant_id in (None, "", "local") or ctx.role in ("org_owner", None):
            raise RuntimeError("no default local tenant or org_owner allowed in hosted mode")
        return ctx
    if ctx is _UNSET:
        return RequestContext()
    return ctx


@contextmanager
def use_context(request_context):
    token = _CURRENT.set(request_context)
    try:
        yield request_context
    finally:
        _CURRENT.reset(token)
