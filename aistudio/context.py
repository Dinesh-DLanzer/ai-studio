"""Request identity carried through local service work. Defaults preserve single-user behavior."""
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
import os
import re


@dataclass(frozen=True)
class RequestContext:
    tenant_id: str = "local"
    actor: str = "local"
    role: object = "org_owner"


def is_hosted():
    return os.environ.get("AISTUDIO_HOSTED", "").lower() in ("1", "true", "yes")


_UNSET = object()
_CURRENT = ContextVar("aistudio_request_context", default=_UNSET)
_TENANT_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def validate_tenant_id(tenant_id):
    if not isinstance(tenant_id, str) or not _TENANT_ID.fullmatch(tenant_id) or tenant_id in (".", "..", "local"):
        raise RuntimeError("invalid tenant id")
    return tenant_id


def get_context():
    ctx = _CURRENT.get()
    if is_hosted():
        if ctx is _UNSET:
            raise RuntimeError("request context must be set explicitly in hosted mode")
        if ctx.tenant_id in (None, "", "local") or ctx.role in ("org_owner", None):
            raise RuntimeError("no default local tenant or org_owner allowed in hosted mode")
        validate_tenant_id(ctx.tenant_id)
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
