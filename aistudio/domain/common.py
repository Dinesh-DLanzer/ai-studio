"""Common definitions, constants and helpers across AI Studio service domains."""
import hashlib
from pathlib import Path
import re

REPO = Path(__file__).resolve().parent.parent.parent
ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
REVIEW_PRICE = 0.003
DOC_FILES = ("Story.md", "brief.md", "TODO.md")
MD_MARK = "\n<!-- kept in sync with the AI Studio visual editor -->\n"


class ServiceError(Exception):
    """A user-facing error (bad input, gate refused, missing file)."""


def _sha(path):
    p = Path(path)
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else ""


def _ident(x, what="id"):
    if not isinstance(x, str) or not ID_RE.match(x):
        raise ServiceError(f"invalid {what}: {x!r}")
    return x
