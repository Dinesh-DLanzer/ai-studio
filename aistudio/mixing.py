"""Loudness, ducking and noise reduction for the export: pure ffmpeg builders plus a local runner.

Everything here is free and local: ffmpeg does the work, no provider is called and nothing leaves
the machine.  The argument builders are pure strings, so they can be checked without ffmpeg; the
runner keeps every path inside the project folder.

The loudness is the standard two-pass loudnorm:
  pass 1 measures the file (print_format=json prints the numbers on stderr),
  pass 2 applies those numbers to the target (-14 LUFS for social, -16 for podcasts, -23 for
  broadcast).  One pass alone cannot hit a target exactly; two passes can.

Contract (tests in tests/test_mixing.py):
  loudness_args(target_lufs=-14, measured=None) -> {"measure": str, "apply": str}
      The two loudnorm filter chains.
  measure_cmd(src, target_lufs=-14, ffmpeg="ffmpeg") -> [argv]
  apply_cmd(src, dst, target_lufs=-14, measured=None, ffmpeg="ffmpeg") -> [argv]
      The complete commands of the two passes (the apply pass copies the video).
  parse_loudnorm(text) -> dict
      The JSON block loudnorm prints (input_i, input_tp, input_lra, input_thresh, target_offset...).
  duck_filter(voice, music, out=None, threshold=0.05, ratio=8, attack=20, release=300) -> str
      The sidechaincompress chain that ducks the music under the voice.
  denoise_filter(nr=12, nf=-25) -> str
      The afftdn noise reduction for the dialogue.
  normalise(src, dst, target_lufs=-14, pdir=None, ffmpeg="ffmpeg") -> {"measured": dict}
      Runs the two passes on a file.  Both paths must stay inside pdir.
"""
import json
import os
import shutil
import subprocess
from pathlib import Path

TP = -1.5                     # the true peak ceiling (dBTP) every target gets
LRA = 11.0                    # the loudness range every target gets
SAMPLE_RATE = 48000           # the delivery sample rate
BITRATE = "192k"
TIMEOUT = 900


class MixError(RuntimeError):
    """ffmpeg is missing, refused the file or the paths left the project."""


def _lufs(value):
    """-14 stays -14, -14.5 stays -14.5 (the loudnorm spelling)."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        raise MixError(f"the loudness target must be a number, not {value!r}") from None
    if -70.0 <= v <= -5.0:
        return f"{v:g}"
    raise MixError(f"the loudness target must be between -70 and -5 LUFS, not {v:g}")


def _num(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def loudness_args(target_lufs=-14, measured=None):
    """The two loudnorm filter chains: the measure pass and the apply pass.
    measured: the numbers the measure pass printed (the 'input_i' family); without them the
    apply pass lets loudnorm do its best in one go."""
    target = _lufs(target_lufs)
    measure = f"loudnorm=I={target}:TP={TP:g}:LRA={LRA:g}:print_format=json"
    apply_ = f"loudnorm=I={target}:TP={TP:g}:LRA={LRA:g}"
    if measured:
        apply_ += (f":measured_I={_fmt(measured.get('input_i'))}"
                   f":measured_TP={_fmt(measured.get('input_tp'))}"
                   f":measured_LRA={_fmt(measured.get('input_lra'))}"
                   f":measured_thresh={_fmt(measured.get('input_thresh'))}"
                   f":offset={_fmt(measured.get('target_offset', measured.get('offset', 0.0)))}"
                   ":linear=true")
    apply_ += ":print_format=summary"
    return {"measure": measure, "apply": apply_}


def _fmt(value):
    """A measured number as loudnorm wants it (the string it printed, or a plain number)."""
    if value is None:
        return "0"
    if isinstance(value, str):
        return value.strip() or "0"
    try:
        return f"{float(value):g}"
    except (TypeError, ValueError):
        return "0"


def measure_cmd(src, target_lufs=-14, ffmpeg="ffmpeg"):
    """The ffmpeg command of the measure pass: it prints the loudness numbers and writes nothing."""
    return [ffmpeg, "-hide_banner", "-nostats", "-nostdin", "-i", str(src),
            "-af", loudness_args(target_lufs)["measure"], "-f", "null", "-"]


def apply_cmd(src, dst, target_lufs=-14, measured=None, ffmpeg="ffmpeg"):
    """The ffmpeg command of the apply pass: the video is copied, only the audio is normalised."""
    return [ffmpeg, "-y", "-hide_banner", "-nostats", "-nostdin", "-i", str(src),
            "-af", loudness_args(target_lufs, measured)["apply"],
            "-ar", str(SAMPLE_RATE), "-c:v", "copy", "-c:a", "aac", "-b:a", BITRATE, str(dst)]


def parse_loudnorm(text):
    """The JSON block loudnorm prints on stderr -> {"input_i", "input_tp", "input_lra",
    "input_thresh", "target_offset", ...}.  {} when there is none."""
    raw = str(text or "")
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end <= start:
        return {}
    try:
        doc = json.loads(raw[start:end + 1])
    except ValueError:
        return {}
    return doc if isinstance(doc, dict) else {}


def _label(name):
    """A filter graph label ('voice' -> '[voice]')."""
    name = str(name or "")
    if not name:
        return ""
    return name if name.startswith("[") else f"[{name}]"


def duck_filter(voice, music, out=None, threshold=0.05, ratio=8, attack=20, release=300):
    """The sidechaincompress chain: the music is compressed by the voice (the sidechain).
    '[music][voice]sidechaincompress=threshold=0.05:ratio=8:attack=20:release=300[ducked]'."""
    out = _label(out) if out else "[ducked]"
    return (f"{_label(music)}{_label(voice)}"
            f"sidechaincompress=threshold={threshold:g}:ratio={ratio:g}:attack={attack:g}:release={release:g}{out}")


def denoise_filter(nr=12, nf=-25):
    """The afftdn noise reduction for the dialogue ('afftdn=nr=12:nf=-25')."""
    return f"afftdn=nr={nr:g}:nf={nf:g}"


def loudnorm_filter(target_lufs=-14):
    """The one-pass loudnorm chain for a filter graph (the two-pass version is exact)."""
    return f"loudnorm=I={_lufs(target_lufs)}:TP={TP:g}:LRA={LRA:g}"


def loudness_for_format(format_id):
    """The loudness target of a format (-14 LUFS for social, -16 for podcasts, -23 for broadcast).
    None when the format does not say."""
    from aistudio import formats
    try:
        value = formats.get_format(format_id).get("loudness")
    except (ValueError, OSError):
        return None
    try:
        value = int(value)
    except (TypeError, ValueError):
        return None
    return value if -70 <= value <= -5 else None


# ---------------------------------------------------------------- the local runner
def _inside(path, root):
    p, r = Path(path).resolve(), Path(root).resolve()
    return p == r or r in p.parents


def run(args, cwd=None, timeout=TIMEOUT):
    """Run a local program.  An argv list only, never a shell."""
    try:
        p = subprocess.run(list(args), capture_output=True, text=True, cwd=str(cwd) if cwd else None,
                           timeout=timeout, stdin=subprocess.DEVNULL, check=False)
    except FileNotFoundError:
        raise MixError(f"{Path(args[0]).name} is not installed (brew install ffmpeg)") from None
    except subprocess.TimeoutExpired:
        raise MixError(f"{Path(args[0]).name} timed out after {timeout}s") from None
    except OSError as e:
        raise MixError(f"could not start {Path(args[0]).name}: {e}") from None
    return p.returncode, p.stdout or "", p.stderr or ""


def normalise(src, dst, target_lufs=-14, pdir=None, ffmpeg="ffmpeg"):
    """Run the two loudnorm passes on a file: measure it, then apply the target.
    Both paths must stay inside pdir (the project).  Returns {"measured": {...}, "target": ...}."""
    src, dst = Path(src), Path(dst)
    if pdir:
        for path in (src, dst):
            if not _inside(path, pdir):
                raise MixError(f"the file must stay inside the project: {path}")
    if not src.is_file():
        raise MixError(f"the file does not exist: {src}")
    if not shutil.which(ffmpeg) and not Path(ffmpeg).is_file():
        raise MixError("ffmpeg is not installed (brew install ffmpeg)")
    rc, out, err = run(measure_cmd(src, target_lufs, ffmpeg))
    measured = parse_loudnorm(err or out)
    if rc != 0 or not measured:
        tail = " ".join((err or out or "").split())[-200:]
        raise MixError(f"ffmpeg could not measure the loudness: {tail}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    rc, out, err = run(apply_cmd(src, dst, target_lufs, measured, ffmpeg))
    if rc != 0 or not dst.is_file():
        tail = " ".join((err or out or "").split())[-200:]
        raise MixError(f"ffmpeg could not normalise the loudness: {tail}")
    return {"measured": measured, "target": _lufs(target_lufs)}


def ffmpeg_path():
    """The ffmpeg program on this machine (None when it is not installed)."""
    return shutil.which("ffmpeg") or (shutil.which("ffmpeg.exe") or None)


def available():
    """Is the local ffmpeg there?  (The mix is free, but it needs the program.)"""
    return bool(ffmpeg_path())


def loudness_of(path, ffmpeg="ffmpeg"):
    """The measured loudness of a file (the measure pass only): {"input_i", ...}."""
    rc, out, err = run(measure_cmd(path, -14, ffmpeg))
    measured = parse_loudnorm(err or out)
    if rc != 0 or not measured:
        raise MixError(f"ffmpeg could not measure the loudness of {path}")
    return measured
