#!/usr/bin/env python3
"""One command to run AI Studio on macOS, Linux or Windows:
- Checks and auto-installs missing dependencies (Node.js/npm, ffmpeg) where possible.
- Creates the Python venv, installs requirements.
- Builds the web UI if needed.
- Starts the local server.
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


def ensure_system_dependencies():
    """Detect and attempt to auto-install missing dependencies (ffmpeg, npm)."""
    has_npm = shutil.which("npm") is not None
    has_ffmpeg = shutil.which("ffmpeg") is not None

    if has_npm and has_ffmpeg:
        return

    print("Checking system dependencies...", flush=True)

    if sys.platform == "darwin":
        # macOS Homebrew
        brew = shutil.which("brew")
        if brew:
            if not has_npm:
                print("Auto-installing Node.js via Homebrew...", flush=True)
                try:
                    subprocess.run([brew, "install", "node"], check=True)
                except Exception as e:
                    print(f"Warning: Failed to install node: {e}", flush=True)
            if not has_ffmpeg:
                print("Auto-installing FFmpeg via Homebrew...", flush=True)
                try:
                    subprocess.run([brew, "install", "ffmpeg"], check=True)
                except Exception as e:
                    print(f"Warning: Failed to install ffmpeg: {e}", flush=True)
        else:
            if not has_npm:
                print("Notice: Node.js (npm) is missing and Homebrew was not found. Please install Node.js from https://nodejs.org", flush=True)
            if not has_ffmpeg:
                print("Notice: FFmpeg is missing. Run `brew install ffmpeg` or download from https://ffmpeg.org", flush=True)

    elif sys.platform.startswith("linux"):
        # Linux package managers
        def try_install_linux(pkg_names):
            if shutil.which("apt-get"):
                sudo = ["sudo"] if os.geteuid() != 0 and shutil.which("sudo") else []
                subprocess.run([*sudo, "apt-get", "update", "-qq"], check=False)
                subprocess.run([*sudo, "apt-get", "install", "-y", "-qq", *pkg_names], check=False)
            elif shutil.which("dnf"):
                sudo = ["sudo"] if os.geteuid() != 0 and shutil.which("sudo") else []
                subprocess.run([*sudo, "dnf", "install", "-y", *pkg_names], check=False)
            elif shutil.which("pacman"):
                sudo = ["sudo"] if os.geteuid() != 0 and shutil.which("sudo") else []
                subprocess.run([*sudo, "pacman", "-S", "--noconfirm", *pkg_names], check=False)

        needed = []
        if not has_npm:
            needed.extend(["nodejs", "npm"])
        if not has_ffmpeg:
            needed.append("ffmpeg")
        if needed:
            print(f"Attempting to install missing packages: {', '.join(needed)}...", flush=True)
            try:
                try_install_linux(needed)
            except Exception as e:
                print(f"Notice: Automatic installation failed: {e}. Please install them manually.", flush=True)

    elif os.name == "nt":
        # Windows winget
        winget = shutil.which("winget")
        if winget:
            if not has_npm:
                print("Auto-installing Node.js LTS via winget...", flush=True)
                try:
                    subprocess.run([winget, "install", "--id", "OpenJS.NodeJS.LTS", "--exact", "--accept-package-agreements", "--accept-source-agreements"], check=False)
                except Exception as e:
                    print(f"Warning: {e}", flush=True)
            if not has_ffmpeg:
                print("Auto-installing FFmpeg via winget...", flush=True)
                try:
                    subprocess.run([winget, "install", "--id", "Gyan.FFmpeg", "--exact", "--accept-package-agreements", "--accept-source-agreements"], check=False)
                except Exception as e:
                    print(f"Warning: {e}", flush=True)


def main():
    if sys.version_info < (3, 10):
        sys.exit("AI Studio needs Python 3.10 or newer.")

    ensure_system_dependencies()

    if not PY.exists():
        print("Creating the Python environment (.venv) ...", flush=True)
        venv.EnvBuilder(with_pip=True).create(VENV)

    print("Installing / updating Python requirements ...", flush=True)
    run([PY, "-m", "pip", "install", "-q", "-r", ROOT / "requirements.txt"])

    npm = shutil.which("npm")
    if npm:
        web_dir = ROOT / "web"
        if not (web_dir / "node_modules").is_dir():
            print("Installing web dependencies ...", flush=True)
            run([npm, "install", "--no-audit", "--no-fund"], cwd=web_dir)
        print("Building the web UI ...", flush=True)
        run([npm, "run", "build"], cwd=web_dir)
    elif not (ROOT / "web" / "dist").is_dir():
        sys.exit("The web UI is not built yet and npm was not found. Install Node.js (https://nodejs.org), then run this again.")

    if not shutil.which("ffmpeg"):
        hint = "brew install ffmpeg" if sys.platform == "darwin" else ("winget install Gyan.FFmpeg" if os.name == "nt" else "sudo apt install ffmpeg")
        print(f"Note: ffmpeg was not found on your PATH. Export Video (Review & Export) and clip frame checks need it ({hint}).", flush=True)

    os.chdir(ROOT)
    if os.name != "nt":
        os.execv(str(PY), [str(PY), "-m", "server.app", *sys.argv[1:]])
    else:
        sys.exit(subprocess.call([str(PY), "-m", "server.app", *sys.argv[1:]]))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
