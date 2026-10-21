"""Free, local FFmpeg clip tools. Commands are always passed as argv lists."""
from functools import lru_cache
import os
import shutil
import subprocess
import tempfile
from pathlib import Path


def _in_test_mode() -> bool:
    return os.environ.get("AISTUDIO_ALL_TEST", "").strip() == "1"


_ASPECTS = {"9:16": (720, 1280), "16:9": (1280, 720), "1:1": (720, 720)}
_BASE_TOOLS = {
    "reframe_local": {"kind": "local", "input": "clip|still", "params": {"aspect": list(_ASPECTS), "mode": ["crop", "pad", "blur-pad"]}},
    "upscale_local": {"kind": "local", "input": "clip|still", "params": {"scale": [2]}},
    "interpolate": {"kind": "local", "input": "clip", "params": {"fps": [48, 60], "slowmo": [2, 4]}},
    "speed": {"kind": "local", "input": "clip", "params": {"factor": [0.5, 0.75, 1.25, 1.5, 2]}},
    "loop": {"kind": "local", "input": "clip", "params": {"times": [2, 3, 4, 5]}},
    "stabilize": {"kind": "local", "input": "clip", "params": {}},
}


@lru_cache(maxsize=1)
def _filters():
    """Read FFmpeg's filter catalog once for this process."""
    if not shutil.which("ffmpeg"):
        return frozenset()
    try:
        result = subprocess.run(["ffmpeg", "-filters"], check=True, capture_output=True, text=True)
    except (OSError, subprocess.SubprocessError):
        return frozenset()
    found = set()
    for line in result.stdout.splitlines():
        cols = line.split()
        if len(cols) >= 2 and len(cols[0]) == 3:
            found.add(cols[1])
    return frozenset(found)


def _has_filter(name):
    return name in _filters()


TOOLS = {k: dict(v) for k, v in _BASE_TOOLS.items() if k != "stabilize" or _has_filter("vidstabdetect")}


def available():
    """Return the local tools supported by the installed FFmpeg."""
    if not shutil.which("ffmpeg"):
        return []
    # Refreshing the registry here also keeps availability correct when the filter probe is reset in tests.
    return [name for name in _BASE_TOOLS if name != "stabilize" or _has_filter("vidstabdetect")]


def _contained(root, path, label):
    root = Path(root).resolve()
    path = Path(path)
    if not path.is_absolute():
        path = root / path
    resolved = path.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"{label} must be inside the project directory") from exc
    return resolved


def _validate(tool, params):
    if tool not in _BASE_TOOLS:
        raise ValueError(f"unknown local tool: {tool}")
    if tool not in available():
        raise ValueError(f"local tool is not available: {tool}")
    if not isinstance(params, dict):
        raise ValueError("params must be an object")
    schema = _BASE_TOOLS[tool]["params"]
    if set(params) != set(schema):
        raise ValueError(f"{tool} parameters must be exactly: {', '.join(schema)}")
    for key, choices in schema.items():
        value = params[key]
        if isinstance(value, bool) or value not in choices:
            raise ValueError(f"invalid {key} for {tool}")


def _version_path(dst):
    dst.parent.mkdir(parents=True, exist_ok=True)
    n = 1
    while True:
        candidate = dst.with_name(f"{dst.stem}.v{n}{dst.suffix}")
        if not candidate.exists():
            return candidate
        n += 1


def _video_filter(tool, params):
    if tool == "reframe_local":
        w, h = _ASPECTS[params["aspect"]]
        if params["mode"] == "crop":
            return f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h}"
        return f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2"
    if tool == "upscale_local":
        return "scale=iw*2:ih*2:flags=lanczos"
    if tool == "interpolate":
        slowmo = params["slowmo"]
        return f"minterpolate=fps={params['fps']},setpts={slowmo}*PTS"
    if tool == "speed":
        return f"setpts={1 / params['factor']:.6g}*PTS"
    return None


def _run(runner, argv):
    result = runner(argv, check=True, capture_output=True, text=True)
    return result


def run_local(tool, src, dst, params, project_dir, runner=subprocess.run):
    """Run a local transform and return its new project-contained version path.

    ``src`` and ``dst`` may be project-relative paths or absolute paths under
    ``project_dir``. ``dst`` is a naming hint; the output gets a free ``.vN``.
    """
    _validate(tool, params)
    root = Path(project_dir).resolve()
    source = _contained(root, src, "source")
    destination = _contained(root, dst, "destination")
    if not source.is_file():
        raise ValueError("source file does not exist")
    output = _version_path(destination)
    if output == source:
        raise ValueError("output cannot overwrite the source")

    # In test mode, return a fake versioned path without running ffmpeg
    if _in_test_mode():
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"fake processed clip")
        return output

    common = ["ffmpeg", "-y", "-nostdin", "-hide_banner", "-loglevel", "error"]
    still_output = destination.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff"}
    if tool == "loop":
        argv = [*common, "-stream_loop", str(params["times"] - 1), "-i", str(source), "-c", "copy", str(output)]
        _run(runner, argv)
        return output
    if tool == "stabilize":
        with tempfile.TemporaryDirectory(prefix="aistudio-vidstab-") as td:
            trf = Path(td) / "transform.trf"
            detect = [*common, "-i", str(source), "-vf", f"vidstabdetect=shakiness=5:accuracy=15:result={trf}", "-f", "null", "-"]
            _run(runner, detect)
            transform = [*common, "-i", str(source), "-vf", f"vidstabtransform=input={trf}:smoothing=10", "-c:v", "libx264", "-c:a", "copy", str(output)]
            _run(runner, transform)
        return output
    if tool == "reframe_local" and params["mode"] == "blur-pad":
        w, h = _ASPECTS[params["aspect"]]
        graph = (f"[0:v]split=2[bg][fg];[bg]scale={w}:{h}:force_original_aspect_ratio=increase,"
                 f"crop={w}:{h},boxblur=20:10[bg];[fg]scale={w}:{h}:force_original_aspect_ratio=decrease[fg];"
                 "[bg][fg]overlay=(W-w)/2:(H-h)/2[v]")
        argv = [*common, "-i", str(source), "-filter_complex", graph, "-map", "[v]"]
        if not still_output:
            argv += ["-map", "0:a?", "-c:v", "libx264", "-c:a", "copy"]
        argv.append(str(output))
    elif tool == "speed":
        speed = params["factor"]
        atempo = []
        remaining = speed
        while remaining > 2:
            atempo.append("atempo=2")
            remaining /= 2
        while remaining < 0.5:
            atempo.append("atempo=0.5")
            remaining /= 0.5
        atempo.append(f"atempo={remaining:g}")
        argv = [*common, "-i", str(source), "-vf", f"setpts={1 / speed:.6g}*PTS", "-af", ",".join(atempo),
                "-c:v", "libx264", "-c:a", "aac", str(output)]
    else:
        vf = _video_filter(tool, params)
        argv = [*common, "-i", str(source), "-vf", vf]
        if not still_output:
            argv += ["-c:v", "libx264", "-c:a", "copy"]
        argv.append(str(output))
    _run(runner, argv)
    return output
