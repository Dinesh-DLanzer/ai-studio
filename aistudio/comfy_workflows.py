"""ComfyUI workflow registry: settings/comfy_workflows/<id>/{workflow_api.json, manifest.json}.
Safe IDs (slug), size caps (<= 2 MB json), validation via comfyui_manifest, delete -> trash dir.
Never executes anything.
"""
import json
import re
import shutil
import time
from pathlib import Path

from aistudio.providers.adapters.comfyui_manifest import (MANIFEST_FILE, WORKFLOW_FILE,
                                                           load_manifest, validate_mapping)
from aistudio.domain.common import ServiceError

MAX_JSON_SIZE = 2 * 1024 * 1024  # 2 MB
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,60}$")


def _slug(text):
    s = re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")[:60]
    return s or "workflow"


def _workflows_root(settings_dir):
    root = Path(settings_dir) / "comfy_workflows"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _trash_root(settings_dir):
    root = Path(settings_dir) / "comfy_workflows" / "_trash"
    root.mkdir(parents=True, exist_ok=True)
    return root


def list_workflows(settings_dir):
    """Return a list of registered workflow manifests (validated)."""
    root = _workflows_root(settings_dir)
    out = []
    for folder in sorted(p for p in root.iterdir() if p.is_dir() and p.name != "_trash"):
        try:
            m = load_manifest(folder)
            out.append({"id": m["id"], "task": m["task"], "inputs": m["inputs"],
                        "profile": m["profile"], "dir": str(folder)})
        except ValueError:
            continue
    return out


def get_workflow(settings_dir, workflow_id):
    """Get a single workflow manifest by ID (validated)."""
    if not ID_RE.match(str(workflow_id or "")):
        raise ServiceError("invalid workflow id")
    folder = _workflows_root(settings_dir) / str(workflow_id)
    if not (folder / MANIFEST_FILE).is_file():
        raise ServiceError("no such workflow")
    try:
        m = load_manifest(folder)
        return {"id": m["id"], "task": m["task"], "inputs": m["inputs"],
                "profile": m["profile"], "workflow": m["workflow"], "dir": str(folder)}
    except ValueError as e:
        raise ServiceError(f"the workflow {workflow_id!r} is not usable: {e}")


def add_workflow(settings_dir, workflow_json, manifest_json):
    """Register a new workflow. Validates the manifest against the workflow."""
    if not isinstance(workflow_json, dict) or not isinstance(manifest_json, dict):
        raise ServiceError("both workflow_json and manifest_json must be objects")
    ident = manifest_json.get("id")
    if not isinstance(ident, str) or not ident.strip():
        raise ServiceError("manifest must have a non-empty 'id'")
    ident = _slug(ident)
    if not ID_RE.match(ident):
        raise ServiceError("workflow id contains invalid characters (use a-z, 0-9, hyphen)")
    root = _workflows_root(settings_dir)
    folder = root / ident
    if folder.exists():
        raise ServiceError(f"workflow {ident!r} already exists")
    # Size check
    wf_bytes = json.dumps(workflow_json).encode("utf-8")
    mf_bytes = json.dumps(manifest_json).encode("utf-8")
    if len(wf_bytes) > MAX_JSON_SIZE:
        raise ServiceError(f"workflow_api.json exceeds {MAX_JSON_SIZE // 1024} KB limit")
    if len(mf_bytes) > MAX_JSON_SIZE:
        raise ServiceError(f"manifest.json exceeds {MAX_JSON_SIZE // 1024} KB limit")
    # Validate the mapping
    try:
        validate_mapping(workflow_json, manifest_json)
    except ValueError as e:
        raise ServiceError(f"manifest validation failed: {e}")
    # Write files
    folder.mkdir(parents=True, exist_ok=True)
    (folder / WORKFLOW_FILE).write_text(json.dumps(workflow_json, indent=2), encoding="utf-8")
    (folder / MANIFEST_FILE).write_text(json.dumps(manifest_json, indent=2), encoding="utf-8")
    return {"id": ident, "task": manifest_json.get("task", "image"), "inputs": manifest_json.get("inputs", {}),
            "profile": manifest_json.get("profile", {}), "dir": str(folder)}


def delete_workflow(settings_dir, workflow_id):
    """Move a workflow to the trash folder (never hard-deletes)."""
    if not ID_RE.match(str(workflow_id or "")):
        raise ServiceError("invalid workflow id")
    root = _workflows_root(settings_dir)
    folder = root / str(workflow_id)
    if not (folder / MANIFEST_FILE).is_file():
        raise ServiceError("no such workflow")
    trash = _trash_root(settings_dir)
    ts = int(time.time() * 1000)
    dest = trash / f"{workflow_id}_{ts}"
    shutil.move(str(folder), str(dest))
    return {"deleted": workflow_id, "trash": str(dest)}


def validate_workflow(settings_dir, workflow_json, manifest_json):
    """Dry-run validation: checks that the manifest maps correctly to the workflow.
    Does not save anything. Returns the validated manifest or raises ServiceError.
    """
    if not isinstance(workflow_json, dict) or not isinstance(manifest_json, dict):
        raise ServiceError("both workflow_json and manifest_json must be objects")
    try:
        validate_mapping(workflow_json, manifest_json)
    except ValueError as e:
        raise ServiceError(f"manifest validation failed: {e}")
    # Also validate the manifest structure by loading it in a temp way
    ident = manifest_json.get("id") or "dry-run"
    try:
        # Create a temp manifest-like dict for validation
        test_manifest = {**manifest_json, "id": ident, "task": manifest_json.get("task", "image"),
                         "inputs": manifest_json.get("inputs", {}),
                         "profile": manifest_json.get("profile", {}),
                         "workflow": workflow_json}
        validate_mapping(workflow_json, test_manifest)
    except ValueError as e:
        raise ServiceError(f"manifest validation failed: {e}")
    return {"ok": True, "id": ident, "task": manifest_json.get("task", "image"),
            "inputs": manifest_json.get("inputs", {}), "profile": manifest_json.get("profile", {})}