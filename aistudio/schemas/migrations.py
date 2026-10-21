"""Pure, forward-only migrations for project documents."""
from copy import deepcopy


CURRENT = {"shots": 2, "images": 2, "edit": 1, "brief": 1, "todos": 1}


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
        version = 1
    if kind == "shots" and version == 1:
        # v2 adds optional direction, end-frame and keyframe fields; identity migration.
        result["schema_version"] = 2
    if kind == "images" and version == 1:
        # v2 adds optional character views/role/consent; identity migration.
        result["schema_version"] = 2
    return result
