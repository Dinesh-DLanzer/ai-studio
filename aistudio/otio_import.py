"""Conservative OTIO-to-edit preview parser; it never writes project files."""
import json
from pathlib import Path
from urllib.parse import unquote, urlparse


def read_otio(text, current_edit, project_dir):
    doc = json.loads(text)
    tracks = (doc.get("tracks") or {}).get("children", [])
    video_track = next((t for t in tracks if t.get("kind") == "Video" or t.get("name") == "Video"), None)
    children = (video_track or {}).get("children", [])
    allowed = {str((Path(project_dir) / c["src"]).resolve()): c["src"] for c in current_edit["tracks"]["video"]}
    result, ignored = [], []
    transition = {"type": "cut", "dur": 0.5}
    for item in children:
        schema = item.get("OTIO_SCHEMA", "")
        if schema.startswith("Transition"):
            transition = {"type": "crossfade", "dur": _duration(item.get("in_offset")) + _duration(item.get("out_offset"))}
            continue
        if not schema.startswith("Clip"):
            continue
        ref = item.get("media_reference") or {}
        parsed = urlparse(ref.get("target_url", ""))
        path = unquote(parsed.path) if parsed.scheme == "file" else ""
        src = allowed.get(str(Path(path).resolve()))
        if src is None:
            ignored.append(item.get("name", ref.get("target_url", "unknown")))
            transition = {"type": "cut", "dur": 0.5}
            continue
        source = item.get("source_range") or {}
        start, duration = _seconds(source.get("start_time")), _seconds(source.get("duration"))
        old = next((x for x in current_edit["tracks"]["video"] if x["src"] == src), {})
        result.append({**old, "src": src, "in": start, "out": start + duration, "transition": transition})
        transition = {"type": "cut", "dur": 0.5}
    updated = json.loads(json.dumps(current_edit))
    updated["tracks"]["video"] = result
    return {"edit": updated, "ignored": ignored,
            "diff": {"before": current_edit["tracks"]["video"], "after": result}}


def _seconds(time):
    if not isinstance(time, dict):
        return 0.0
    value = time.get("value", 0)
    rate = time.get("rate", 1)
    return float(value) / float(rate or 1)


def _duration(value):
    return _seconds(value)
