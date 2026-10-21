"""Blender integration domain: camera-move classification, shot direction and headless previs.

Everything here runs on the server, so it is testable without Blender:
  * the add-on sends sampled camera world matrices, the server classifies the move
    (dolly, truck, orbit, pan, tilt, zoom...) and proposes a direction -- nothing is saved;
  * a human applies the direction to a shot through the schema-validated save path (with history);
  * a previs render runs headless Blender on a .blend inside the project and writes the frames
    into the project's previs/ folder.  Those frames are NOT registered as stills: that stays a
    human action through the normal upload path.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

from aistudio.domain.common import ServiceError
from aistudio.engines import blender as blender_engine
from aistudio.storyboard import camera_classify
from aistudio.storyboard.direction import validate_direction

MAX_CAMERA_SAMPLES = 2000        # a shot is seconds long: 2000 samples is already a lot
MAX_LENS_SAMPLES = 2000
MAX_PREVIS_SHOTS = 200
MAX_FPS = 1000.0
PREVIS_DIR = "previs"
PREVIS_IMAGE_EXT = (".png", ".jpg", ".jpeg", ".webp")


def _number(value, what):
    """A finite number (NaN and inf are refused: they poison the classification)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ServiceError(f"{what} must be a number")
    v = float(value)
    if not math.isfinite(v):
        raise ServiceError(f"{what} must be a finite number")
    return v


def _matrix(sample, index):
    """One camera sample: a 4x4 matrix, or {"frame": n, "matrix": [[...]]}."""
    m = sample
    if isinstance(sample, dict):
        m = sample.get("matrix")
        if m is None:
            m = sample.get("matrix_world")
    if not isinstance(m, (list, tuple)) or len(m) != 4:
        raise ServiceError(f"sample {index}: the camera matrix must have 4 rows")
    rows = []
    for r, row in enumerate(m):
        if not isinstance(row, (list, tuple)) or len(row) != 4:
            raise ServiceError(f"sample {index}: row {r} of the camera matrix must have 4 numbers")
        rows.append([_number(v, f"sample {index}: matrix row {r}") for v in row])
    return rows


def _focal(sample, index):
    """One lens sample: a focal length in mm, or {"focal_length": mm, ...}."""
    if isinstance(sample, dict):
        for key in ("focal_length", "lens_mm", "focal", "value"):
            if sample.get(key) is not None:
                return _number(sample[key], f"lens sample {index}: focal length")
        raise ServiceError(f"lens sample {index}: no focal length")
    return _number(sample, f"lens sample {index}: focal length")


def _target(value):
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise ServiceError("target must be three numbers (x, y, z)")
    return [_number(v, "target") for v in value]


class BlenderDomain:
    """Server side of the Blender add-on and of the headless previs engine."""

    def __init__(self, ws):
        self.ws = ws

    # ---------------------------------------------------------------- camera move
    def camera_move(self, name, shot_id, payload):
        """Classify a sampled camera move and propose a direction.  Nothing is saved.

        payload: {"samples": [4x4 matrices or {"frame": n, "matrix": [...]}], "fps": 24.0,
                  "lens_samples"?: [focal lengths or {"focal_length": mm}], "target"?: [x, y, z]}
        """
        payload = payload or {}
        if not isinstance(payload, dict):
            raise ServiceError("the camera move body must be an object")
        self._shot(name, shot_id)          # the shot must exist

        raw = payload.get("samples")
        if raw is None:
            raw = payload.get("matrices")
        if not isinstance(raw, (list, tuple)) or not raw:
            raise ServiceError("samples are required: send the sampled camera matrices")
        if len(raw) > MAX_CAMERA_SAMPLES:
            raise ServiceError(f"too many samples: {len(raw)} (at most {MAX_CAMERA_SAMPLES})")
        matrices = [_matrix(s, i) for i, s in enumerate(raw)]

        fps = _number(payload.get("fps", 24.0), "fps")
        if fps <= 0 or fps > MAX_FPS:
            raise ServiceError(f"fps must be between 0 and {MAX_FPS:g}")

        lens_raw = payload.get("lens_samples")
        lens = None
        if lens_raw is not None:
            if not isinstance(lens_raw, (list, tuple)):
                raise ServiceError("lens_samples must be a list")
            if len(lens_raw) > MAX_LENS_SAMPLES:
                raise ServiceError(f"too many lens samples: {len(lens_raw)} (at most {MAX_LENS_SAMPLES})")
            lens = [_focal(s, i) for i, s in enumerate(lens_raw)]

        target = _target(payload["target"]) if payload.get("target") is not None else None

        result = camera_classify.classify(matrices, fps=fps, lens_samples=lens, target=target)
        direction = self._proposed_direction(result, lens)
        return {"shot": shot_id, "classification": result, "direction": direction, "saved": False}

    @staticmethod
    def _proposed_direction(result, lens):
        """The direction the classification proposes (validated, never saved here)."""
        direction = {"movement": result["movement"], "speed": result["speed"]}
        if lens:
            focal = lens[0]
            if focal > 0:
                direction["lens_mm"] = focal
        validate_direction(direction)
        return direction

    # ---------------------------------------------------------------- direction
    def apply_direction(self, name, shot_id, direction, replace=False):
        """Apply a validated direction to a shot through the schema-validated save path."""
        if not isinstance(direction, dict):
            raise ServiceError("direction must be an object")
        p = self.ws.pdir(name)
        doc = self.ws._read(p, "shots.json", {"shots": []})
        shot = self._shot(name, shot_id, doc)
        current = dict(shot.get("direction") or {})
        merged = dict(direction) if replace else {**current, **direction}
        try:
            validate_direction(merged)
        except ValueError as e:
            raise ServiceError(str(e)) from None
        shot["direction"] = merged
        self.ws.put_shots(name, doc)        # validates the document and keeps the history
        return {"shot": shot_id, "direction": merged}

    def _shot(self, name, shot_id, doc=None):
        p = self.ws.pdir(name)
        doc = doc if doc is not None else self.ws._read(p, "shots.json", {"shots": []})
        for s in doc.get("shots", []):
            if s.get("id") == shot_id:
                return s
        raise ServiceError(f"unknown shot: {shot_id}")

    # ---------------------------------------------------------------- previs
    def plan_previs(self, name, blend, shots):
        """Validate a headless previs request.  Returns the payload the job runs."""
        p = self.ws.pdir(name).resolve()
        rel = str(blend or "").strip()
        if not rel:
            raise ServiceError("blend is required: the .blend file inside the project")
        path = Path(rel)
        if path.is_absolute() or (len(rel) > 1 and rel[1] == ":"):
            raise ServiceError("the blend file must be a project-relative path")
        if ".." in path.parts:
            raise ServiceError("the blend file must be a project-relative path")
        if path.suffix.lower() != ".blend":
            raise ServiceError("the blend file must be a .blend file")
        target = (p / path).resolve()
        if target != p and p not in target.parents:
            raise ServiceError("the blend file must be inside the project")
        if not target.is_file():
            raise ServiceError(f"no such file in the project: {rel}")

        if shots is None:
            shots = []
        if not isinstance(shots, (list, tuple)):
            raise ServiceError("shots must be a list of shot ids")
        if len(shots) > MAX_PREVIS_SHOTS:
            raise ServiceError(f"too many shots: {len(shots)} (at most {MAX_PREVIS_SHOTS})")
        doc = self.ws._read(p, "shots.json", {"shots": []})
        known = {s.get("id") for s in doc.get("shots", [])}
        ids = []
        for s in shots:
            sid = str(s).strip()
            if not sid:
                continue
            if sid not in known:
                raise ServiceError(f"unknown shot: {sid}")
            if sid not in ids:
                ids.append(sid)
        if not ids:
            raise ServiceError("choose at least one shot to render")
        return {"blend": path.as_posix(), "shots": ids}

    def run_previs(self, name, payload, progress=None):
        """Render the blocking frames with headless Blender (a free local job)."""
        p = self.ws.pdir(name).resolve()
        payload = payload or {}
        blend = (p / str(payload.get("blend", ""))).resolve()
        if p not in blend.parents:
            raise ServiceError("the blend file must be inside the project")
        out_dir = p / PREVIS_DIR
        out_dir.mkdir(parents=True, exist_ok=True)
        if progress:
            progress(10)
        results = blender_engine.run_previs(
            blend=blend,
            out_dir=out_dir,
            shots=list(payload.get("shots") or []),
            project_dir=p,
            blender_bin=self._blender_binary(),
            timeout=int(payload.get("timeout") or 600),
        )
        if progress:
            progress(90)
        frames = []
        for r in results or []:
            if not isinstance(r, dict):
                continue
            frame = str(r.get("frame") or "")
            if frame:
                try:
                    rel = Path(frame).resolve().relative_to(p).as_posix()
                except ValueError:
                    rel = ""
                if rel:
                    r = {**r, "frame": rel}
            frames.append(r)
        return {"out_dir": PREVIS_DIR, "frames": frames, "shots": list(payload.get("shots") or [])}

    def list_previs(self, name):
        """The frames rendered into the project's previs/ folder (never registered automatically)."""
        p = self.ws.pdir(name)
        out = p / PREVIS_DIR
        images = self.ws._read(p, "images.json", {"images": []}).get("images", [])
        registered = {str(i.get("out") or "") for i in images}
        frames = []
        if out.is_dir():
            for f in sorted(out.iterdir()):
                if not f.is_file() or f.name.startswith("."):
                    continue
                rel = f"{PREVIS_DIR}/{f.name}"
                frames.append({
                    "file": rel,
                    "name": f.name,
                    "shot": f.stem,
                    "bytes": f.stat().st_size,
                    "image": f.suffix.lower() in PREVIS_IMAGE_EXT,
                    "registered": rel in registered,
                })
        return {"out_dir": PREVIS_DIR, "outputs": frames}

    def _blender_binary(self):
        """An optional configured Blender path (settings/blender.json); None means auto-detect."""
        f = Path(self.ws.settings_dir) / "blender.json"
        if not f.is_file():
            return None
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        binary = data.get("binary") if isinstance(data, dict) else None
        return str(binary) if isinstance(binary, str) and binary.strip() else None
