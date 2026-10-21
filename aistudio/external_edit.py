"""Safe, local handoff of project media to an approved desktop editor."""
import hashlib
import os
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path


def allowed_apps(apps=None):
    """Return the OS-default choice plus configured application names."""
    return {None, *(str(app) for app in (apps or ()) if isinstance(app, str) and app.strip())}


def _inside(path, root):
    resolved = Path(path).resolve()
    root = Path(root).resolve()
    try:
        resolved.relative_to(root)
    except ValueError:
        return False
    return True


def open_file(path, app=None, *, project_dir=None, allowed=None, platform=sys.platform,
              runner=subprocess.run, startfile=None):
    """Open a file using argv-only platform APIs after enforcing path/app policy."""
    path = Path(path).absolute()
    if project_dir is not None and not _inside(path, project_dir):
        raise ValueError("file is outside the project directory")
    if not path.is_file():
        raise ValueError("file does not exist")
    if app not in allowed_apps(allowed):
        raise ValueError("application is not allowed")
    if platform == "darwin":
        argv = ["open", str(path)] if app is None else ["open", "-a", app, str(path)]
        result = runner(argv, check=False, capture_output=True)
        if getattr(result, "returncode", 0):
            raise OSError("could not open file")
    elif platform.startswith("win"):
        if app is not None:
            raise ValueError("named applications are not supported on Windows")
        (startfile or os.startfile)(str(path))
    elif platform.startswith("linux"):
        if app is not None:
            raise ValueError("named applications are not supported on Linux")
        result = runner(["xdg-open", str(path)], check=False, capture_output=True)
        if getattr(result, "returncode", 0):
            raise OSError("could not open file")
    else:
        raise ValueError("unsupported platform")
    return path


def _sha(path):
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _kind(path):
    from aistudio import imageconv, importzip
    try:
        with open(path, "rb") as f:
            head = f.read(16)
    except OSError:
        return None
    image = imageconv.detect(head)
    if image in ("png", "jpg", "webp"):
        return image
    suffix = Path(path).suffix.lower()
    if suffix in importzip.MAGIC and importzip.MAGIC[suffix](head):
        if suffix in (".png", ".jpg", ".jpeg", ".webp"):
            return {".jpeg": "jpg", ".jpg": "jpg"}.get(suffix, suffix[1:])
        if suffix in (".wav", ".mp3", ".m4a", ".flac"):
            return "audio"
        if suffix in (".mp4", ".mov", ".m4v", ".webm"):
            return "video"
    if head.startswith(b"fLaC") and suffix == ".flac":
        return "audio"
    return None


class ExternalEdit:
    def __init__(self, project_dir=None, *, apps=(), clock=time.monotonic, poll_interval=2,
                 max_duration=2 * 60 * 60, opener=open_file, runner=subprocess.run):
        self.project_dir = Path(project_dir).resolve() if project_dir is not None else None
        self.apps = allowed_apps(apps)
        self.clock, self.poll_interval = clock, float(poll_interval)
        self.max_duration, self.opener, self.runner = float(max_duration), opener, runner
        self.session = None

    def start(self, rel_file, app=None):
        if self.project_dir is None:
            raise ValueError("project directory is required")
        if app not in self.apps:
            raise ValueError("application is not allowed")
        source = (self.project_dir / rel_file).resolve()
        if not _inside(source, self.project_dir) or not source.is_file():
            raise ValueError("file is outside the project or does not exist")
        kind = _kind(source)
        if kind is None:
            raise ValueError("unsupported or invalid media file")
        external = self.project_dir / ".external"
        external.mkdir(exist_ok=True)
        target = external / (uuid.uuid4().hex + source.suffix.lower())
        shutil.copy2(source, target)
        stat = target.stat()
        self.session = {"path": target, "original": source, "kind": kind, "app": app,
                        "baseline": (stat.st_mtime_ns, stat.st_size), "sha256": _sha(target),
                        "started": self.clock(), "last": None, "stable_since": None, "reported": False}
        self.opener(target, app=app, project_dir=self.project_dir, allowed=self.apps - {None})
        return {key: self.session[key] for key in ("path", "sha256", "app")}

    def poll(self):
        s = self.session
        if s is None or s["reported"]:
            return None
        now = self.clock()
        if now - s["started"] >= self.max_duration:
            self.stop()
            return None
        try:
            st = s["path"].stat()
        except OSError:
            return None
        current = (st.st_mtime_ns, st.st_size)
        if current == s["baseline"]:
            s["last"], s["stable_since"] = None, None
            return None
        if current != s["last"]:
            s["last"], s["stable_since"] = current, now
            return None
        if now - s["stable_since"] < 2 * self.poll_interval:
            return None
        s["reported"] = True
        return {"path": s["path"], "app": s["app"], "sha256": _sha(s["path"])} if self.validate(s["path"]) else None

    def validate(self, path):
        s = self.session
        if s is None or not _inside(path, self.project_dir):
            return False
        path = Path(path)
        if not path.is_file() or _kind(path) != s["kind"]:
            return False
        if s["kind"] in ("png", "jpg", "webp"):
            try:
                from PIL import Image
                with Image.open(path) as im:
                    im.verify()
                return True
            except Exception:
                return False
        if s["kind"] == "video":
            try:
                from aistudio.editor import probe
                return probe(path) is not None
            except Exception:
                return False
        return True

    def stop(self):
        self.session = None


def register_version(project_dir, original_rel, new_path, app=None):
    """Copy an edited artifact to the next unused version path, preserving source."""
    root = Path(project_dir).resolve()
    original = (root / original_rel).resolve()
    source = Path(new_path).resolve()
    if not _inside(original, root) or not original.is_file():
        raise ValueError("original is outside the project or missing")
    if not source.is_file():
        raise ValueError("edited file is missing")
    stem, suffix = original.stem, original.suffix
    n = 1
    while True:
        dest = original.with_name(f"{stem}.v{n}{suffix}")
        if not dest.exists():
            break
        n += 1
    shutil.copy2(source, dest)
    return dest, {"tool": "external", "app": app, "source_sha": _sha(source)}
