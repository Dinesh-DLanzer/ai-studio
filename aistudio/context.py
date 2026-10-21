"""Request identity carried through local service work. Defaults preserve single-user behavior."""
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass


@dataclass(frozen=True)
class RequestContext:
    tenant_id: str = "local"
    actor: str = "local"
    role: object = "org_owner"


_CURRENT = ContextVar("aistudio_request_context", default=RequestContext())


def get_context():
    return _CURRENT.get()


@contextmanager
def use_context(request_context):
    token = _CURRENT.set(request_context)
    try:
        yield request_context
    finally:
        _CURRENT.reset(token)
