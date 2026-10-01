"""Delete / export a whole project.  NEVER removes a file: delete MOVES the folder to <workspace>/_trash/<name>__<time>/ so it can be restored.
Standard library only.
"""
import re
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
TRASH_RE = re.compile(r"^([A-Za-z0-9_-]{1,64})__(\d{8}-\d{6})(?:_(\d+))?$")


class TrashError(Exception):
    pass


def trash_dir(root):
    return Path(root) / "_trash"


def move_to_trash(root, name):
    """Move projects/<name> to _trash/<name>__<YYYYmmdd-HHMMSS>.  Returns the trash id (folder name)."""
    if not NAME_RE.match(name or ""):
        raise TrashError(f"invalid project name: {name!r}")
    src = Path(root) / "projects" / name
    if not src.is_dir() or src.is_symlink():
        raise TrashError(f"no such project: {name}")
    td = trash_dir(root)
    td.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    tid, n = f"{name}__{stamp}", 2
    while (td / tid).exists():
        tid = f"{name}__{stamp}_{n}"
        n += 1
    src.rename(td / tid)
    return tid


def list_trash(root):
    out = []
    td = trash_dir(root)
    if td.is_dir():
        for d in sorted(td.iterdir(), reverse=True):
            m = TRASH_RE.match(d.name)
            if d.is_dir() and m:
                when = datetime.strptime(m.group(2), "%Y%m%d-%H%M%S").isoformat(timespec="seconds")
                out.append({"id": d.name, "name": m.group(1), "when": when, "files": sum(1 for f in d.rglob("*") if f.is_file())})
    return out


def restore(root, tid, as_name=None):
    """Move a trashed project back.  Refuses if a project with that name exists unless as_name gives a free one."""
    m = TRASH_RE.match(tid or "")
    src = trash_dir(root) / tid if m else None
    if not m or not src.is_dir():
        raise TrashError("unknown trash item")
    name = as_name or m.group(1)
    if not NAME_RE.match(name):
        raise TrashError(f"invalid project name: {name!r}")
    dst = Path(root) / "projects" / name
    if dst.exists():
        raise TrashError(f"a project called {name} already exists; restore it under another name")
    src.rename(dst)
    return name


def zip_project(pdir, include_discarded=False):
    """Write the project folder to a temporary zip (entries start with '<name>/').  Skips symlinks; skips _discarded unless asked.
    Returns the zip's path; the caller deletes it after sending."""
    pdir = Path(pdir)
    fd = tempfile.NamedTemporaryFile(prefix=f"aistudio-{pdir.name}-", suffix=".zip", delete=False)
    fd.close()
    with zipfile.ZipFile(fd.name, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(pdir.rglob("*")):
            rel = f.relative_to(pdir)
            if f.is_symlink() or not f.is_file() or (not include_discarded and "_discarded" in rel.parts):
                continue
            z.write(f, Path(pdir.name) / rel)
    return Path(fd.name)
