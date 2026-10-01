"""Import a project from a zip (the file "Export Project" makes).  Everything is checked BEFORE anything is installed; nothing is run.
Standard library only.

Checks (all problems are collected and reported together, nothing is half-imported):
  * it is a real zip, small enough, not a zip bomb (limits on files, total size, compression ratio; sizes are counted while writing, not trusted),
  * every entry is safe: relative, no '..', no backslash or control characters, not a symlink, not too deep,
  * one project: a single top-level folder (what Export makes) or the files at the top; macOS junk (__MACOSX, .DS_Store) is ignored,
  * only known file types (json, md, csv, txt, images, video, audio); no scripts, programs or html; media files must start with the right magic bytes,
  * the JSON files parse; shots.json, images.json and edit.json pass the same validators the app uses,
  * what the zip must NOT be able to do: proposals.json (approved paid actions) is dropped and the budget approval is reset,
    so a human approves spending again on this computer.
"""
import json
import re
import shutil
import stat
import tempfile
import zipfile
from pathlib import Path

from aistudio import editor, kind as kind_mod, project as project_mod

NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
LIMITS = {"files": 5000, "total": 4 * 1024**3, "ratio": 300, "depth": 6, "path": 200}
TEXT = {".json", ".md", ".csv", ".txt"}
FAKE_VIDEO = b"FAKEMP4"     # the placeholder clip that test mode writes (a project made in test mode must round-trip)
MAGIC = {  # suffix -> check on the first 16 bytes
    ".png": lambda b: b.startswith(b"\x89PNG\r\n\x1a\n"),
    ".jpg": lambda b: b.startswith(b"\xff\xd8\xff"), ".jpeg": lambda b: b.startswith(b"\xff\xd8\xff"),
    ".webp": lambda b: b[:4] == b"RIFF" and b[8:12] == b"WEBP",
    ".mp4": lambda b: b[4:8] == b"ftyp" or b.startswith(FAKE_VIDEO), ".mov": lambda b: b[4:8] in (b"ftyp", b"moov", b"wide", b"mdat", b"free") or b.startswith(FAKE_VIDEO),
    ".m4v": lambda b: b[4:8] == b"ftyp" or b.startswith(FAKE_VIDEO),
    ".webm": lambda b: b.startswith(b"\x1a\x45\xdf\xa3"),
    ".mp3": lambda b: b.startswith(b"ID3") or (len(b) > 1 and b[0] == 0xFF and b[1] & 0xE0 == 0xE0),
    ".wav": lambda b: b[:4] == b"RIFF" and b[8:12] == b"WAVE", ".m4a": lambda b: b[4:8] == b"ftyp", ".aac": lambda b: len(b) > 1 and b[0] == 0xFF and b[1] & 0xF0 == 0xF0 or b.startswith(b"ID3"),
    ".ogg": lambda b: b.startswith(b"OggS"),
}
JUNK = ("__MACOSX", ".DS_Store", "Thumbs.db", ".git")
KNOWN_JSON = ("shots.json", "images.json", "edit.json", "budget.json", "brief.json", "chat.json", "todos.json", "verify.json", "discarded.json", "sandbox.json", "proposals.json")


class ImportError_(Exception):
    """The zip was refused.  .problems lists every reason (strings safe to show)."""
    def __init__(self, problems):
        self.problems = problems if isinstance(problems, list) else [problems]
        super().__init__("; ".join(self.problems))


def _norm(raw):
    """Entry name -> clean posix parts, or raise ValueError with the reason."""
    if "\\" in raw or any(ord(c) < 32 for c in raw):
        raise ValueError("has a backslash or control character")
    p = Path(raw)
    if p.is_absolute() or raw.startswith("/") or ".." in p.parts:
        raise ValueError("is not a safe relative path")
    return [x for x in p.parts if x not in (".",)]


def _is_junk(parts):
    """Skipped silently: macOS/Windows litter and our own leftovers (.rejected uploads, .tmp saves)."""
    return any(x in JUNK or x.startswith("._") for x in parts) or parts[-1].endswith((".rejected", ".tmp"))


def inspect(zpath):
    """Open the zip and return (zipfile, root_prefix_parts, members) after the structural checks.  Raises ImportError_."""
    zpath = Path(zpath)
    if not zipfile.is_zipfile(zpath):
        raise ImportError_("This is not a zip file.")
    z = zipfile.ZipFile(zpath)
    problems, members = [], []
    infos = z.infolist()
    if len(infos) > LIMITS["files"]:
        raise ImportError_(f"The zip has {len(infos)} entries; the limit is {LIMITS['files']}.")
    total = 0
    for i in infos:
        try:
            parts = _norm(i.filename)
        except ValueError as e:
            problems.append(f"{i.filename!r} {e}")
            continue
        if not parts or _is_junk(parts):
            continue
        if stat.S_ISLNK(i.external_attr >> 16):
            problems.append(f"{i.filename} is a symbolic link, which is not allowed")
            continue
        if i.is_dir():
            continue
        if len(parts) > LIMITS["depth"] + 1 or len(i.filename) > LIMITS["path"]:
            problems.append(f"{i.filename} is nested too deep or the name is too long")
            continue
        if i.flag_bits & 0x1:
            problems.append(f"{i.filename} is password protected")
            continue
        total += i.file_size
        members.append((i, parts))
    if total > LIMITS["total"]:
        problems.append(f"The unpacked project would be {total // 1024**2} MB; the limit is {LIMITS['total'] // 1024**2} MB.")
    comp = sum(i.compress_size for i, _ in members) or 1
    if total > 50 * 1024**2 and total / comp > LIMITS["ratio"]:
        problems.append("The zip is compressed suspiciously well (possible zip bomb).")
    if problems:
        raise ImportError_(problems)
    if not members:
        raise ImportError_("The zip is empty.")
    tops = {parts[0] for _, parts in members}
    top_files = [p for _, p in members if len(p) == 1]
    root = [next(iter(tops))] if len(tops) == 1 and not top_files else []
    return z, root, members


def derive_name(zpath_name, root):
    """Suggested project name: the top folder in the zip, else the zip's file name; made safe."""
    base = root[0] if root else Path(zpath_name or "project").stem
    base = re.sub(r"[^A-Za-z0-9_-]+", "-", base).strip("-_")[:64]
    return base or "project"


def extract_and_validate(zpath, tmp_root):
    """Unpack into a new temp folder under tmp_root and validate it.  Returns (folder, notes).  Raises ImportError_ (temp folder removed)."""
    z, root, members = inspect(zpath)
    dest = Path(tempfile.mkdtemp(prefix="import-", dir=tmp_root))
    problems, notes, written, n = [], [], 0, len(root)
    try:
        for info, parts in members:
            rel = parts[n:]
            if not rel:
                continue
            rel_s = "/".join(rel)
            suffix = Path(rel[-1]).suffix.lower()
            if suffix not in TEXT and suffix not in MAGIC:
                problems.append(f"{rel_s}: file type {suffix or '(none)'} is not allowed (only json, md, csv, txt, images, video and audio)")
                continue
            target = dest.joinpath(*rel)
            target.parent.mkdir(parents=True, exist_ok=True)
            head, size = b"", 0
            with z.open(info) as src, open(target, "wb") as out:
                while True:
                    chunk = src.read(1 << 20)
                    if not chunk:
                        break
                    if not head:
                        head = chunk[:16]
                    size += len(chunk)
                    written += len(chunk)
                    if written > LIMITS["total"]:
                        raise ImportError_("The project is bigger than the size limit once unpacked.")
                    out.write(chunk)
            if suffix in MAGIC:
                if size == 0 or not MAGIC[suffix](head):
                    problems.append(f"{rel_s}: is not a real {suffix[1:]} file (the content does not match the name)")
            elif suffix in (".json",):
                try:
                    json.loads(target.read_text(encoding="utf-8"))
                except (ValueError, UnicodeDecodeError):
                    problems.append(f"{rel_s}: is not valid JSON")
            else:
                try:
                    target.read_text(encoding="utf-8")
                except UnicodeDecodeError:
                    problems.append(f"{rel_s}: is not UTF-8 text")
        problems += _check_project(dest)
        if problems:
            raise ImportError_(problems)
        notes += _sanitise(dest)
        return dest, notes
    except Exception:
        shutil.rmtree(dest, ignore_errors=True)
        raise
    finally:
        z.close()


def _load(dest, fn):
    f = dest / fn
    return json.loads(f.read_text(encoding="utf-8")) if f.is_file() else None


def _check_project(dest):
    errs = []
    has = lambda fn: (dest / fn).is_file()
    if not (has("shots.json") or has("Story.md")):
        errs.append("This does not look like an AI Studio project: it has neither shots.json nor Story.md.")
    for fn in KNOWN_JSON:
        if has(fn):
            try:
                d = _load(dest, fn)
            except (ValueError, UnicodeDecodeError):
                continue                       # already reported as invalid JSON
            if fn in ("shots.json", "images.json", "edit.json", "budget.json", "brief.json", "sandbox.json") and not isinstance(d, dict):
                errs.append(f"{fn}: must be a JSON object")
            elif fn in ("chat.json", "todos.json", "discarded.json", "proposals.json", "verify.json") and not isinstance(d, (dict, list)):
                errs.append(f"{fn}: has the wrong shape")
    for fn, check in (("shots.json", project_mod.validate_shots), ("images.json", project_mod.validate_images)):
        if has(fn) and isinstance(_safe(dest, fn), dict):
            errs += [f"{fn}: {e}" for e in check(_safe(dest, fn))]
    if has("edit.json") and isinstance(_safe(dest, "edit.json"), dict):
        try:
            doc = editor.clean(_safe(dest, "edit.json"))
            for it in doc["tracks"]["video"] + doc["tracks"]["audio"]:
                if not (dest / it["src"]).is_file():
                    errs.append(f"edit.json: uses {it['src']}, which is not in the zip")
        except editor.EditError as e:
            errs.append(f"edit.json: {e}")
    doc = _safe(dest, "shots.json")
    if isinstance(doc, dict) and isinstance(doc.get("shots"), list):
        for s in doc["shots"]:
            fc = s.get("final_clip") if isinstance(s, dict) else None
            if fc:
                try:
                    p = Path(fc)
                    if p.is_absolute() or ".." in p.parts:
                        errs.append(f"shots.json: final_clip {fc!r} is not a safe path")
                    elif not (dest / fc).is_file():
                        errs.append(f"shots.json: final_clip {fc} is not in the zip")
                except (TypeError, ValueError):
                    errs.append("shots.json: bad final_clip")
    return errs


def _safe(dest, fn):
    try:
        return _load(dest, fn)
    except (ValueError, UnicodeDecodeError):
        return None


def _sanitise(dest):
    """Remove everything that could carry an approval from another computer.  Returns notes for the user."""
    notes = []
    real, test = kind_mod.evidence(dest)
    sb = dest / "sandbox.json"
    if sb.exists() and real:
        sb.unlink()
        notes.append("The zip marked this as a test project, but it contains real generated media or real costs, so it was imported as an actual project.")
    elif real:
        notes.append("Imported as an actual project (it has real generated media or real costs).")
    elif sb.exists() or test:
        notes.append("Imported as a test project (nothing real was generated in it).")
    pf = dest / "proposals.json"
    if pf.exists():
        pf.unlink()
        notes.append("Approvals and pending paid actions from the zip were dropped (proposals.json). Approve spending again here.")
    bf = dest / "budget.json"
    if bf.exists():
        b = json.loads(bf.read_text(encoding="utf-8"))
        if isinstance(b, dict) and b.get("approved"):
            b["approved"] = False
            bf.write_text(json.dumps(b, indent=2, ensure_ascii=False), encoding="utf-8")
            notes.append("The budget approval was reset. Approve the budget again before generating anything.")
    return notes


def install(root, folder, name):
    """Move the validated folder to <root>/projects/<name>.  Refuses to overwrite."""
    if not NAME_RE.match(name or ""):
        raise ImportError_(f"Invalid project name {name!r}: use letters, numbers, - and _ (up to 64).")
    dst = Path(root) / "projects" / name
    if dst.exists():
        raise ImportError_(f"A project called {name} already exists. Choose another name.")
    for d in ("stills", "clips"):
        (folder / d).mkdir(exist_ok=True)
    folder.rename(dst)
    return dst
