#!/usr/bin/env python3
"""One command to run AI Studio on macOS, Linux or Windows: makes the Python venv, installs requirements, builds the web UI if needed, starts the server.

    python3 scripts/start.py        (Windows: py scripts\\start.py   or just double-click scripts\\start.bat)
Needs Python 3.10+; Node.js/npm only the first time (to build the web UI), and ffmpeg on your PATH for the clip checks (macOS can use swift instead).
"""
import os
import shutil
import subprocess
import sys
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VENV = ROOT / ".venv"
PY = VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def run(cmd, **kw):
    subprocess.run([str(c) for c in cmd], check=True, **kw)


def main():
    if sys.version_info < (3, 10):
        sys.exit("AI Studio needs Python 3.10 or newer.")
    if not PY.exists():
        print("Creating the Python environment (.venv) ...", flush=True)
        venv.EnvBuilder(with_pip=True).create(VENV)
    run([PY, "-m", "pip", "install", "-q", "-r", ROOT / "requirements.txt"])
    if not (ROOT / "web" / "dist").is_dir():
        npm = shutil.which("npm")
        if not npm:
            sys.exit("The web UI is not built yet and npm was not found. Install Node.js (https://nodejs.org), then run this again.")
        print("Building the web UI (first run only) ...", flush=True)
        run([npm, "install", "--no-audit", "--no-fund"], cwd=ROOT / "web")
        run([npm, "run", "build"], cwd=ROOT / "web")
    if not shutil.which("ffmpeg"):
        hint = "brew install ffmpeg" if sys.platform == "darwin" else "install it with your package manager"
        print(f"Note: ffmpeg was not found on your PATH. Export Video (Review & Export) and clip frame checks need it ({hint}).", flush=True)
    os.chdir(ROOT)
    os.execv(str(PY), [str(PY), "-m", "server.app"]) if os.name != "nt" else sys.exit(subprocess.call([str(PY), "-m", "server.app"]))


if __name__ == "__main__":
    main()
