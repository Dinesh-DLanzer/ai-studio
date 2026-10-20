"""ComfyUI workflow manifests: load a workflow folder and map AI Studio inputs onto ComfyUI nodes.  Standard library only.

A ComfyUI workflow folder (e.g. <workspace>/settings/comfy_workflows/wan-i2v/) holds two files:
  workflow_api.json   the workflow exported from ComfyUI with "Save (API)":
                      {"3": {"class_type": "KSampler", "inputs": {"seed": 123, ...}},
                       "6": {"class_type": "CLIPTextEncode", "inputs": {"text": "...", "clip": ["4", 1]}}}
  manifest.json       {"id": "wan-i2v", "task": "image_to_video",
                       "inputs": {"prompt": ["6", "text"], "start_frame": ["52", "image"],
                                  "seconds": ["50", "length", "frames@16"], "seed": ["3", "seed"]},
                       "profile": {"durations": [3, 5], "resolutions": ["480p", "720p"],
                                   "frames": {"start": true, "end": false}, "camera": {"mode": "prompt"}}}

manifest["inputs"] maps an AI Studio input name to a target [node_id, input_name] or
[node_id, input_name, transform]:
  "frames@16"   seconds -> frames  (int(round(seconds * 16)))
  "frames"      the value already is a number of frames
  "int" / "str" the value is converted
  (no transform) the value is written as it is
Every mapped node AND input must exist in workflow_api.json: a mapping that points at a node the workflow does
not have, or at an input that node does not have, raises ValueError naming the node and the input.

load_manifest(dir)          -> {"id", "task", "inputs", "profile", "workflow", "dir"}   (validated; ValueError on any problem)
apply_inputs(workflow, manifest, values) -> a NEW workflow with `values` written into the mapped nodes
list_manifests(root)        -> the manifests of every workflow folder under `root` (invalid folders are skipped)
"""
import copy
import json
from pathlib import Path

MANIFEST_FILE = "manifest.json"
WORKFLOW_FILE = "workflow_api.json"


def _read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except OSError as e:
        raise ValueError("cannot read %s: %s" % (path, e))
    except ValueError as e:
        raise ValueError("%s is not valid JSON: %s" % (path, e))


def _parse_target(target, name):
    """A mapping target -> (node_id, input_name, transform|None).  Raises ValueError when it is malformed."""
    if isinstance(target, dict):                       # {"node": "6", "input": "text"} is accepted too
        target = [target.get("node"), target.get("input"), target.get("transform")]
    if not isinstance(target, (list, tuple)) or len(target) not in (2, 3):
        raise ValueError("manifest input %r must map to [node_id, input_name] or [node_id, input_name, transform]" % name)
    node_id = str(target[0]) if target[0] is not None else ""
    input_name = str(target[1]) if target[1] is not None else ""
    transform = target[2] if len(target) == 3 and target[2] not in (None, "") else None
    if not node_id:
        raise ValueError("manifest input %r has no node id" % name)
    if not input_name:
        raise ValueError("manifest input %r has no input name" % name)
    if transform is not None and not isinstance(transform, str):
        raise ValueError("manifest input %r has a transform that is not a string" % name)
    return node_id, input_name, transform


def validate_workflow(workflow):
    """The workflow must be an API-format object of nodes.  Raises ValueError otherwise."""
    if not isinstance(workflow, dict) or not workflow:
        raise ValueError("the workflow must be a non-empty object of nodes")
    for node_id, node in workflow.items():
        if not isinstance(node, dict):
            raise ValueError("node %r in the workflow is not an object" % node_id)
        if not isinstance(node.get("inputs"), dict):
            raise ValueError("node %r in the workflow has no inputs object" % node_id)


def validate_mapping(workflow, manifest):
    """Every mapped node and input must exist in the workflow.  Raises ValueError naming what is missing."""
    validate_workflow(workflow)
    inputs = manifest.get("inputs") if isinstance(manifest, dict) else None
    if not isinstance(inputs, dict):
        raise ValueError("the manifest 'inputs' must be an object")
    for name, target in inputs.items():
        node_id, input_name, _ = _parse_target(target, name)
        node = workflow.get(node_id)
        if node is None:
            raise ValueError("manifest input %r points at node %r, which the workflow does not have" % (name, node_id))
        if input_name not in (node.get("inputs") or {}):
            raise ValueError("manifest input %r points at %s.%s, which that node does not have"
                             % (name, node_id, input_name))


def _transform_value(transform, value, name):
    if transform is None:
        return value
    if transform == "frames":
        return int(round(float(value)))
    if transform.startswith("frames@"):
        try:
            fps = float(transform.split("@", 1)[1])
        except ValueError:
            raise ValueError("manifest input %r has an unknown transform %r" % (name, transform))
        return int(round(float(value) * fps))
    if transform == "int":
        return int(value)
    if transform == "str":
        return str(value)
    raise ValueError("manifest input %r has an unknown transform %r" % (name, transform))


def load_manifest(directory):
    """Load and validate the workflow folder `directory` (manifest.json + workflow_api.json)."""
    folder = Path(directory)
    manifest_path = folder / MANIFEST_FILE
    workflow_path = folder / WORKFLOW_FILE
    if not manifest_path.is_file():
        raise ValueError("no %s in %s" % (MANIFEST_FILE, folder))
    if not workflow_path.is_file():
        raise ValueError("no %s in %s" % (WORKFLOW_FILE, folder))
    manifest = _read_json(manifest_path)
    workflow = _read_json(workflow_path)
    if not isinstance(manifest, dict):
        raise ValueError("%s must be an object" % manifest_path)
    ident = manifest.get("id")
    if not isinstance(ident, str) or not ident.strip():
        raise ValueError("%s has no 'id'" % manifest_path)
    task = manifest.get("task") or "image"
    if not isinstance(task, str):
        raise ValueError("%s has a 'task' that is not a string" % manifest_path)
    profile = manifest.get("profile")
    if profile is None:
        profile = {}
    if not isinstance(profile, dict):
        raise ValueError("%s has a 'profile' that is not an object" % manifest_path)
    inputs = manifest.get("inputs")
    if inputs is None:
        inputs = {}
    if not isinstance(inputs, dict):
        raise ValueError("%s has an 'inputs' that is not an object" % manifest_path)
    validate_workflow(workflow)
    out = {"id": ident.strip(), "task": task.strip() or "image", "inputs": inputs,
           "profile": profile, "workflow": workflow, "dir": str(folder)}
    validate_mapping(workflow, out)
    return out


def list_manifests(root):
    """The manifests of every workflow folder under `root`; folders that do not load are skipped."""
    base = Path(root)
    if not base.is_dir():
        return []
    out = []
    for folder in sorted(p for p in base.iterdir() if p.is_dir()):
        try:
            out.append(load_manifest(folder))
        except ValueError:
            continue
    return out


def apply_inputs(workflow, manifest, values):
    """A copy of `workflow` with `values` (AI Studio inputs) written into the nodes the manifest maps.

    A value that the manifest does not map is ignored (the workflow default stays) and a None value is ignored.
    The workflow that is passed in is never modified.
    """
    validate_mapping(workflow, manifest)
    out = copy.deepcopy(workflow)
    inputs = manifest.get("inputs") or {}
    for name, value in (values or {}).items():
        target = inputs.get(name)
        if target is None or value is None:
            continue
        node_id, input_name, transform = _parse_target(target, name)
        out[node_id]["inputs"][input_name] = _transform_value(transform, value, name)
    return out
