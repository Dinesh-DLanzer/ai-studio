"""Blender engine integration for AI Studio.

Discovers the Blender binary, constructs secure non-shell command invocations,
and executes headless previs rendering with project path boundary containment.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Callable, Sequence

DEFAULT_BLENDER_PATHS = [
    # macOS
    "/Applications/Blender.app/Contents/MacOS/Blender",
    os.path.expanduser("~/Applications/Blender.app/Contents/MacOS/Blender"),
    # Linux
    "/usr/bin/blender",
    "/usr/local/bin/blender",
    "/snap/bin/blender",
    os.path.expanduser("~/.local/bin/blender"),
    # Windows
    r"C:\Program Files\Blender Foundation\Blender 4.2\blender.exe",
    r"C:\Program Files\Blender Foundation\Blender 4.1\blender.exe",
    r"C:\Program Files\Blender Foundation\Blender 4.0\blender.exe",
    r"C:\Program Files\Blender Foundation\Blender\blender.exe",
]


def find_blender(configured: str | Path | None = None) -> str | None:
    """Find Blender executable path.

    Order of priority:
    1. Explicitly configured path (if valid executable)
    2. PATH environment variable via shutil.which
    3. Platform-specific standard installation locations

    Returns:
        Absolute path to Blender executable, or None if not found.
    """
    if configured:
        p_str = os.path.expanduser(str(configured))
        if os.path.isfile(p_str) and os.access(p_str, os.X_OK):
            return os.path.abspath(p_str)

    # Check system PATH
    which_path = shutil.which("blender")
    if which_path:
        return which_path

    # Check common fallback locations
    for candidate in DEFAULT_BLENDER_PATHS:
        cand_str = os.path.expanduser(str(candidate))
        if os.path.isfile(cand_str) and os.access(cand_str, os.X_OK):
            return cand_str

    return None


def build_command(
    blend: str | Path,
    script: str | Path,
    args: Sequence[str],
    blender_bin: str | Path | None = None,
) -> list[str]:
    """Build argv command list for headless Blender script execution.

    Runs Blender in background mode (-b) without GUI, executing the specified
    python script (-P), and passing arguments after the '--' separator.
    """
    bin_path = str(blender_bin or find_blender() or "blender")
    cmd = [
        bin_path,
        "-b",
        str(blend),
        "-P",
        str(script),
        "--",
    ]
    cmd.extend(str(a) for a in args)
    return cmd


def run_previs(
    blend: str | Path,
    out_dir: str | Path,
    shots: Sequence[Any] | str,
    runner: Callable[..., Any] | Any = None,
    timeout: int = 600,
    project_dir: str | Path | None = None,
    blender_bin: str | Path | None = None,
) -> list[dict[str, Any]]:
    """Execute headless Blender previs rendering for specified shots.

    Enforces that `out_dir` resides inside `project_dir` to prevent directory traversal.
    Collects and parses JSON outputs emitted by the bundled script matching 'AISTUDIO_JSON:'.

    Args:
        blend: Path to .blend file.
        out_dir: Directory where rendered frames will be saved.
        shots: List of shot IDs or shot dictionaries (e.g. ['s01', 's02']).
        runner: Execution callable, defaults to subprocess.run.
        timeout: Execution timeout in seconds (default: 600).
        project_dir: Project root directory for path containment validation.
        blender_bin: Optional explicit path to Blender binary.

    Returns:
        List of parsed JSON dictionaries emitted by the render script.

    Raises:
        FileNotFoundError: If blender executable cannot be found.
        ValueError: If out_dir is outside project_dir.
        RuntimeError: If the render process fails.
    """
    # Accommodate flexible positional arguments: runner vs project_dir
    if runner is not None and not callable(runner) and (isinstance(runner, (str, Path)) or project_dir is None):
        project_dir = runner
        runner = subprocess.run
    elif runner is None:
        runner = subprocess.run

    # Enforce path containment
    if project_dir is not None:
        out_resolved = Path(out_dir).resolve()
        proj_resolved = Path(project_dir).resolve()
        try:
            out_resolved.relative_to(proj_resolved)
        except ValueError:
            raise ValueError(
                f"Output directory '{out_dir}' is outside project directory '{project_dir}'"
            )

    # Locate binary
    bin_path = find_blender(blender_bin)
    if not bin_path:
        raise FileNotFoundError(
            "Blender executable not found. Please install Blender or configure its path."
        )

    # Prepare bundled script path and arguments
    script_path = Path(__file__).parent / "blender_previs_script.py"

    shot_list = [shots] if isinstance(shots, (str, bytes)) else list(shots)
    script_args: list[str] = ["--out", str(out_dir)]
    for shot in shot_list:
        if isinstance(shot, dict):
            sid = shot.get("id") or shot.get("shot_id") or shot.get("name") or str(shot)
        else:
            sid = str(shot)
        script_args.extend(["--shot", sid])

    cmd = build_command(blend, script_path, script_args, blender_bin=bin_path)

    res = runner(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
    )

    if hasattr(res, "returncode") and res.returncode != 0:
        stderr = getattr(res, "stderr", "")
        raise RuntimeError(f"Blender previs failed with exit code {res.returncode}: {stderr}")

    stdout = getattr(res, "stdout", "") or ""
    results: list[dict[str, Any]] = []
    for line in stdout.splitlines():
        trimmed = line.strip()
        if trimmed.startswith("AISTUDIO_JSON:"):
            payload = trimmed[len("AISTUDIO_JSON:"):].strip()
            if payload:
                results.append(json.loads(payload))

    return results
