"""Workspace-wide, rebuildable index of generated and reusable project media."""
import hashlib
import json
import re
import shutil
import time
import uuid
from datetime import datetime
from pathlib import Path, PurePosixPath

from . import costlog, store

MEDIA = {"stills": "image", "clips": "clip", "audio": "audio"}


def _ensure_fts(root):
    try:
        store.execute(root, "CREATE VIRTUAL TABLE IF NOT EXISTS items_fts USING fts5(id UNINDEXED, prompt, project, model)")
        return True
    except Exception:
        return False


def _sha(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _safe_project(root, project):
    projects = (Path(root) / "projects").resolve()
    p = (projects / str(project)).resolve()
    if p.parent != projects or not p.is_dir() or p.name.startswith(("_", ".")):
        raise ValueError("invalid project")
    return p


def _safe_rel(pdir, rel):
    rel = PurePosixPath(str(rel))
    if rel.is_absolute() or ".." in rel.parts or not rel.parts:
        raise ValueError("invalid project path")
    path = (pdir / Path(*rel.parts)).resolve()
    if not path.is_relative_to(pdir.resolve()):
        raise ValueError("path outside project")
    return path, rel.as_posix()


def _upsert(root, data):
    data = {"tenant_id": "local", "actor": "local", "favorite": 0, "params": "{}", "meta": "{}", **data}
    # Stable identity lets rebuilds retain favorites; changed bytes produce a new version.
    ident = hashlib.sha256((data["project"] + "\0" + data["file"] + "\0" + data["sha"]).encode()).hexdigest()[:32]
    data["id"] = ident
    store.execute(root, """INSERT INTO items (id,tenant_id,actor,project,kind,category,file,sha,prompt,model,provider,seed,params,cost,status,favorite,created,meta)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(tenant_id,actor,project,file,sha) DO UPDATE SET
        kind=excluded.kind,category=excluded.category,prompt=excluded.prompt,model=excluded.model,provider=excluded.provider,
        seed=excluded.seed,params=excluded.params,cost=excluded.cost,status=excluded.status,created=excluded.created,meta=excluded.meta""",
        tuple(data[k] for k in ("id", "tenant_id", "actor", "project", "kind", "category", "file", "sha", "prompt", "model", "provider", "seed", "params", "cost", "status", "favorite", "created", "meta")))
    _ensure_fts(root)
    if _ensure_fts(root):
        store.execute(root, "DELETE FROM items_fts WHERE id=?", (ident,))
        store.execute(root, "INSERT INTO items_fts (id,prompt,project,model) VALUES (?,?,?,?)", (ident, data["prompt"], data["project"], data["model"]))
    return get(root, ident)


def _upsert_many(root, items):
    ready = []
    for data in items:
        data = {"tenant_id": "local", "actor": "local", "favorite": 0, "params": "{}", "meta": "{}", **data}
        data["id"] = hashlib.sha256((data["project"] + "\0" + data["file"] + "\0" + data["sha"]).encode()).hexdigest()[:32]
        ready.append(data)
    if not ready: return []
    sql = """INSERT INTO items (id,tenant_id,actor,project,kind,category,file,sha,prompt,model,provider,seed,params,cost,status,favorite,created,meta)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(tenant_id,actor,project,file,sha) DO UPDATE SET
        kind=excluded.kind,category=excluded.category,prompt=excluded.prompt,model=excluded.model,provider=excluded.provider,
        seed=excluded.seed,params=excluded.params,cost=excluded.cost,status=excluded.status,created=excluded.created,meta=excluded.meta"""
    has_fts = _ensure_fts(root)
    with store.transaction(root) as tx:
        for d in ready:
            tx.execute(sql, tuple(d[k] for k in ("id", "tenant_id", "actor", "project", "kind", "category", "file", "sha", "prompt", "model", "provider", "seed", "params", "cost", "status", "favorite", "created", "meta")))
        if has_fts:
            tx.execute("DELETE FROM items_fts")
            for d in ready: tx.execute("INSERT INTO items_fts (id,prompt,project,model) VALUES (?,?,?,?)", (d["id"], d["prompt"], d["project"], d["model"]))
    ids = [d["id"] for d in ready]
    found = {r["id"]: r for r in store.query(root, "SELECT * FROM items WHERE id IN (" + ",".join("?" for _ in ids) + ")", ids)}
    return [found[i] for i in ids if i in found]


def _from_file(root, project, pdir, file, meta=None, log=None, commit=True):
    path, rel = _safe_rel(pdir, file)
    if not path.is_file():
        return None
    meta = meta or {}
    log = log or {}
    kind = MEDIA.get(PurePosixPath(rel).parts[0], "asset")
    status = "discarded" if "_discarded" in PurePosixPath(rel).parts else ("failed" if str(log.get("result", "")).lower().startswith(("failed", "error", "output_failed")) else str(meta.get("status") or "completed"))
    values = dict(project=project, kind=meta.get("kind", kind), category=meta.get("category", kind), file=rel,
                  sha=_sha(path), prompt=str(meta.get("prompt") or log.get("prompt") or ""), model=str(meta.get("model") or log.get("model") or ""),
                  provider=str(meta.get("provider") or log.get("provider") or ""), seed=str(meta.get("seed") or ""),
                  params=json.dumps(meta.get("params") or {}, sort_keys=True), cost=_float(log.get("cost", meta.get("cost", 0))), status=status,
                  created=_time(meta.get("created", log.get("timestamp", path.stat().st_mtime))), meta=json.dumps(meta, sort_keys=True))
    return _upsert(root, values) if commit else values


def _float(v):
    try: return float(v or 0)
    except (ValueError, TypeError): return 0.0


def _time(v):
    try: return float(v)
    except (ValueError, TypeError):
        try: return datetime.fromisoformat(str(v).replace("Z", "+00:00")).timestamp()
        except (ValueError, TypeError): return time.time()


def _log_rows(pdir):
    logpath = pdir / "cost_log.csv"
    rows = costlog.read_log(pdir) if not logpath.is_symlink() else []
    discarded = []
    try:
        dpath = pdir / "discarded.json"
        if not dpath.is_symlink(): discarded = json.loads(dpath.read_text(encoding="utf-8"))
    except Exception: pass
    out = {}
    for row in rows:
        shot, stage, attempt = row.get("shot", ""), row.get("stage", ""), row.get("attempt", "")
        suffix = {"image": ".png", "clip": ".mp4", "audio": ".mp3"}.get(stage, "")
        candidate = f"{stage}s/{shot}{suffix}" if stage != "image" else f"stills/{shot}.png"
        # Match actual files later by shot stem, retain cost rows with no successful file as failures/history.
        out.setdefault(shot, []).append((row, candidate, any(PurePosixPath(x.get("file", "")).name.startswith(shot) for x in discarded)))
    return out


def rebuild(root):
    root = Path(root).resolve()
    projects = root / "projects"
    pending = []
    if not projects.is_dir(): return []
    for pdir in projects.iterdir():
        if not pdir.is_dir() or pdir.name.startswith(("_", ".")) or pdir.name == ".history" or pdir.resolve().parent != projects.resolve(): continue
        logs = _log_rows(pdir)
        seen_log = set()
        for folder, kind in MEDIA.items():
            media_dir = pdir / folder
            if not media_dir.is_dir(): continue
            for f in media_dir.rglob("*"):
                rel = f.relative_to(pdir).as_posix()
                if not f.is_file() or any(x in ("_trash", ".history") for x in f.parts): continue
                if f.name.endswith(".meta.json"): continue
                try: _safe_rel(pdir, rel)
                except ValueError: continue
                mpath = f.with_name(f.name + ".meta.json")
                try: _safe_rel(pdir, mpath.relative_to(pdir).as_posix())
                except ValueError: mpath = None
                try: meta = json.loads(mpath.read_text(encoding="utf-8")) if mpath.is_file() else {}
                except Exception: meta = {}
                shot = f.stem.split("_", 1)[0]
                logrow = {}
                if shot in logs:
                    logrow = logs[shot][0][0]
                    seen_log.add(shot)
                item = _from_file(root, pdir.name, pdir, rel, meta, logrow, commit=False)
                if item: pending.append(item)
        for shot, entries in logs.items():
            for i, (r, candidate, discarded) in enumerate(entries):
                if r.get("result", "").lower().startswith(("failed", "error", "output_failed")) or (discarded and shot not in seen_log):
                    rel = f"_history/costlog-{shot}-{r.get('stage','')}-{r.get('attempt','')}-{i}"
                    data = dict(project=pdir.name, kind=r.get("stage") or "unknown", category=r.get("stage") or "unknown", file=rel, sha=hashlib.sha256(json.dumps(r, sort_keys=True).encode()).hexdigest(),
                                prompt=r.get("prompt", ""), model=r.get("model", ""), provider=r.get("provider", ""), seed="", params="{}", cost=_float(r.get("cost")),
                                status="failed" if r.get("result", "").lower().startswith(("failed", "error", "output_failed")) else "discarded", created=_time(r.get("timestamp")), meta=json.dumps(r, sort_keys=True))
                    pending.append(data)
    return _upsert_many(root, pending)


def index_output(root, project, rel_file):
    pdir = _safe_project(root, project)
    path, rel = _safe_rel(pdir, rel_file)
    if not path.is_file(): raise FileNotFoundError(rel)
    mp = path.with_name(path.name + ".meta.json")
    try: meta = json.loads(mp.read_text(encoding="utf-8")) if mp.exists() else {}
    except Exception: meta = {}
    return _from_file(root, pdir.name, pdir, rel, meta)


def _matches(row, filters):
    for key, col in (("type", "kind"), ("project", "project"), ("model", "model")):
        if filters.get(key) and row[col] != filters[key]: return False
    if filters.get("favorite") is not None and bool(row["favorite"]) != bool(filters["favorite"]): return False
    if filters.get("failed") is not None and (row["status"] == "failed") != bool(filters["failed"]): return False
    if filters.get("date_from") is not None and row["created"] < _time(filters["date_from"]): return False
    if filters.get("date_to") is not None and row["created"] > _time(filters["date_to"]): return False
    if filters.get("cost_min") is not None and row["cost"] < _float(filters["cost_min"]): return False
    if filters.get("cost_max") is not None and row["cost"] > _float(filters["cost_max"]): return False
    return True


def search(root, q="", filters=None, limit=50, offset=0):
    filters = filters or {}
    allrows = store.query(root, "SELECT * FROM items ORDER BY created DESC")
    query = str(q or "").lower()
    fts = _ensure_fts(root) if query else False
    ids = set()
    if fts:
        try: ids = {r["id"] for r in store.query(root, "SELECT id FROM items_fts WHERE items_fts MATCH ?", (query,))}
        except Exception: ids = set()
    selected = [r for r in allrows if (not query or (r["id"] in ids if ids else query in " ".join((r["prompt"], r["project"], r["model"])).lower())) and _matches(r, filters)]
    return {"items": selected[max(0,int(offset)):max(0,int(offset))+max(1,min(int(limit),500))], "total": len(selected), "limit": int(limit), "offset": int(offset)}


def get(root, ident):
    rows = store.query(root, "SELECT * FROM items WHERE id=?", (str(ident),))
    return rows[0] if rows else None


def set_favorite(root, ident, on):
    store.execute(root, "UPDATE items SET favorite=? WHERE id=?", (int(bool(on)), str(ident)))
    return get(root, ident)


def stats(root):
    rows = store.query(root, "SELECT COUNT(*) AS count, COALESCE(SUM(cost),0) AS cost FROM items")
    return rows[0]


def _require_consent(pdir, src, meta):
    """Real-person assets travel only with a human-recorded consent entry (aistudio/consent.py) in the project that is the source or target."""
    from aistudio import consent
    stem = Path(src).stem.split(".v")[0]
    flagged = bool(meta.get("real_person"))
    try:
        images_doc = json.loads((Path(pdir) / "images.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        images_doc = {"images": []}
    if flagged:
        consent.require(pdir, meta.get("subject") or stem)
    consent.require_assets(pdir, images_doc, [stem])


def promote(root, project, rel_file):
    pdir = _safe_project(root, project)
    src, rel = _safe_rel(pdir, rel_file)
    if not src.is_file(): raise FileNotFoundError(rel)
    row = index_output(root, project, rel)
    meta_path = src.with_name(src.name + ".meta.json")
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.is_file() else {}
    _require_consent(pdir, src, meta)
    cat = re.sub(r"[^a-z0-9_-]+", "-", str(row["category"]).lower()).strip("-") or "asset"
    slug = re.sub(r"[^a-z0-9_-]+", "-", src.stem.lower()).strip("-") or "asset"
    folder = Path(root) / "library" / cat
    folder.mkdir(parents=True, exist_ok=True)
    dest = folder / f"{slug}{src.suffix.lower()}"
    n = 2
    while dest.exists(): dest = folder / f"{slug}-{n}{src.suffix.lower()}"; n += 1
    shutil.copy2(src, dest)
    if meta_path.is_file(): shutil.copy2(meta_path, dest.with_name(dest.name + ".meta.json"))
    return _from_file(root, "_library", Path(root) / "library", dest.relative_to(Path(root) / "library").as_posix(), meta)


def use_in_project(root, library_id, project, kind):
    row = get(root, library_id)
    if not row: raise ValueError("no such library item")
    src = Path(root) / "library" / row["file"]
    if not src.is_file(): raise FileNotFoundError(row["file"])
    if row.get("project") != "_library": raise ValueError("only workspace library items can be used in a project")
    pdir = _safe_project(root, project)
    folder = {"image": "stills", "clip": "clips", "audio": "audio"}.get(kind)
    if not folder: raise ValueError("kind must be image, clip, or audio")
    allowed = {"image": {".png", ".jpg", ".jpeg", ".webp"}, "clip": {".mp4", ".mov", ".webm"}, "audio": {".wav", ".mp3", ".m4a", ".flac"}}[kind]
    if src.suffix.lower() not in allowed: raise ValueError(f"a {src.suffix.lower()} file cannot be used as {kind}")
    mp0 = src.with_name(src.name + ".meta.json")
    meta0 = json.loads(mp0.read_text(encoding="utf-8")) if mp0.is_file() else {}
    _require_consent(pdir, src, meta0)
    outdir = pdir / folder
    if outdir.is_symlink() or not outdir.resolve().is_relative_to(pdir.resolve()) if outdir.exists() else False:
        raise ValueError("project media folder must stay inside the project")
    outdir.mkdir(parents=True, exist_ok=True)
    stem, ext = src.stem, src.suffix
    dest = outdir / f"{stem}{ext}"; n = 2
    while dest.exists(): dest = outdir / f"{stem}-{n}{ext}"; n += 1
    shutil.copy2(src, dest)
    mp = src.with_name(src.name + ".meta.json")
    if mp.is_file(): shutil.copy2(mp, dest.with_name(dest.name + ".meta.json"))
    item = index_output(root, project, dest.relative_to(pdir).as_posix())
    return item


def remix(root, library_id, project):
    row = get(root, library_id)
    if not row: raise ValueError("no such library item")
    meta = json.loads(row.get("meta") or "{}")
    kind = row["kind"] if row["kind"] in ("image", "clip", "audio") else "image"
    return {"kind": kind, "target": PurePosixPath(row["file"]).stem, "project": project, "prompt": row["prompt"], "model": row["model"],
            "params": json.loads(row["params"] or "{}"), "refs": meta.get("refs", []), "source_library_id": row["id"]}
