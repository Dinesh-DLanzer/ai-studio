"""E6: extract N frames spread across the WHOLE clip (seeking past ~4 s is unreliable, so the Swift helper decodes sequentially)."""
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent


class FrameError(Exception):
    pass


def plan_command(video, outdir, n, seconds, which=shutil.which, platform=sys.platform):
    """Return the command list to run (pure; testable)."""
    if n < 1:
        raise ValueError("n must be >= 1")
    if which("ffmpeg"):
        return ["ffmpeg", "-y", "-loglevel", "error", "-i", str(video), "-vf", f"fps={n}/{max(seconds, 1)}", str(Path(outdir) / "f%02d.png")]
    if platform == "darwin" and which("swift"):
        return ["swift", str(HERE / "tools" / "frames.swift"), str(video), str(outdir), str(n)]
    raise FrameError("Need ffmpeg (or macOS with swift) to extract frames")


def extract(video, outdir, n=8, seconds=4):
    Path(outdir).mkdir(parents=True, exist_ok=True)
    cmd = plan_command(video, outdir, n, seconds)
    subprocess.run(cmd, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    frames = sorted(str(p) for p in Path(outdir).glob("*.png"))
    if not frames:
        raise FrameError(f"no frames produced from {video}")
    return frames
