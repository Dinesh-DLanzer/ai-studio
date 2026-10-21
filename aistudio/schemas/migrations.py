"""Pure, forward-only migrations for project documents."""
from copy import deepcopy


CURRENT = {"shots": 1, "images": 1, "edit": 1, "brief": 1, "todos": 1}


def migrate(kind, doc):
    """Return a migrated copy of a document, never modifying *doc*."""
    if kind not in CURRENT:
        raise ValueError(f"unknown document kind: {kind}")
    if not isinstance(doc, dict):
        raise TypeError("document must be an object")
    result = deepcopy(doc)
    version = result.get("schema_version", 0)
    if not isinstance(version, int) or isinstance(version, bool) or version < 0:
        raise ValueError(f"invalid schema_version for {kind}: {version!r}")
    if version > CURRENT[kind]:
        raise ValueError(f"unsupported {kind} schema_version: {version}")
    if version == 0:
        result["schema_version"] = 1
    return result
