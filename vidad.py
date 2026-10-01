#!/usr/bin/env python3
"""vidad - cost-gated video ad generation on OpenRouter. Standard library only.

Commands:
  models                          list video models, durations, resolutions (free)
  new <project>                   create a project folder from templates
  estimate <project> [options]    pre-flight budget (writes budget.json)
  run <project> <shot> --stage draft|final [--dry-run] [--override]
  approve <project> <shot> draft|final
  sync <project>                  resolve timed-out/interrupted jobs (real cost + clip)
  image <project> <id> [--dry-run]  generate a still from images.json with Qwen Image 3 (costs ~$0.04)
  check <project> <shot>          save frames across the WHOLE clip to review (extra people, text, cut-offs)
  discard <project> <file> -m why move a clip/still to a _discarded folder and record its cost
  costs <project>                 spend split: USED vs DISCARDED
  lastframe <project> <shot>      save the last frame of a shot's latest clip to stills/last_frames/
  status <project>                per-shot state + spend vs budget
  report <project>                actual vs estimated, measured failure rate
"""
import argparse, base64, csv, json, mimetypes, shutil, subprocess, sys, time, urllib.request, urllib.error
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).parent
API = "https://openrouter.ai/api/v1"
IMAGE_MODEL = "qwen/qwen-image-3"
STOP_LOSS = 1.30      # pause at 130% of estimate
MAX_FINAL_RETRIES = 2 # retries after the first final attempt
LOG_COLS = ["timestamp", "shot", "stage", "model", "resolution", "seconds", "attempt", "job_id", "cost", "result"]


def load_env():
    """The OpenRouter key saved in AI Studio (Settings > AI Providers). There is no .env file or environment variable for keys."""
    sys.path.insert(0, str(HERE))
    from aistudio.secrets import SecretStore
    key = SecretStore().get("openrouter").get("api_key", "")
    if not key:
        sys.exit("No OpenRouter key saved. Start AI Studio, open Settings > AI Providers and add OpenRouter.")
    return key


def call(method, path, key, body=None, raw=False):
    req = urllib.request.Request(API + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            data = r.read()
            return data if raw else json.loads(data)
    except urllib.error.HTTPError as e:
        sys.exit(f"HTTP {e.code} from {path}: {e.read().decode()[:500]}")


def project_dir(name):
    p = HERE / "projects" / name
    if not p.exists():
        sys.exit(f"No such project: {p}. Run: python3 vidad.py new {name}")
    return p


def read_json(p, default=None):
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default


def write_json(p, obj):
    p.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")


def read_log(pdir):
    f = pdir / "cost_log.csv"
    if not f.exists():
        return []
    with f.open() as fh:
        return list(csv.DictReader(fh))


def append_log(pdir, row):
    f = pdir / "cost_log.csv"
    new = not f.exists()
    with f.open("a", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=LOG_COLS)
        if new:
            w.writeheader()
        w.writerow(row)


def spent(pdir):
    return sum(float(r["cost"] or 0) for r in read_log(pdir))


def rates():
    return read_json(HERE / "rates.json")


def rate_for(model, res, secs=None, audio=False):
    """USD/second. rates.json value may be a number, {"audio": x, "no_audio": y},
    or a duration-tier list [{"up_to": 8, "rate": x}, {"rate": y}] (first tier with secs <= up_to wins)."""
    r = rates()["models"].get(model)
    if not r or res not in r:
        sys.exit(f"No rate for {model} @ {res} in rates.json. Add it (check `python3 vidad.py models` and OpenRouter pricing).")
    v = r[res]
    if isinstance(v, dict):
        v = v["audio" if audio else "no_audio"]
    if isinstance(v, list):
        if secs is None:
            sys.exit(f"{model} @ {res} has duration tiers; a duration is required.")
        v = next((t["rate"] for t in v if "up_to" not in t or secs <= t["up_to"]), None)
        if v is None:
            sys.exit(f"{model} @ {res}: no tier covers {secs}s in rates.json.")
    return v


# ---------------------------------------------------------------- commands
def cmd_models(a):
    key = load_env()
    data = call("GET", "/videos/models", key)
    items = data.get("data", data) if isinstance(data, dict) else data
    for m in items:
        print(f"{m.get('id')}\n  durations: {m.get('supported_durations')}  res: {m.get('supported_resolutions')}"
              f"  aspect: {m.get('supported_aspect_ratios')}")
    print("\nCopy the model ids you want into rates.json and shots.json.")


def cmd_new(a):
    p = HERE / "projects" / a.project
    if p.exists():
        sys.exit("Project already exists.")
    (p / "clips").mkdir(parents=True)
    (p / "stills").mkdir()
    for t in ("brief.md", "shots.json", "Story.md", "TODO.md", "images.json"):
        src = HERE / "templates" / t
        if src.exists():
            (p / t).write_text(src.read_text(encoding="utf-8").replace("{{PROJECT}}", a.project), encoding="utf-8")
    print(f"Created {p}\nNext: fill in brief.md and Story.md, list images in images.json, edit shots.json, then estimate.")


def cmd_estimate(a):
    pdir = project_dir(a.project)
    d = read_json(pdir / "shots.json")
    shots, audio = d["shots"], d.get("audio", False)
    fres, skip = d.get("final_resolution", "720p"), d.get("skip_draft", False)
    f = a.failure
    if not 0 <= f < 0.9:
        sys.exit("--failure must be between 0 and 0.9")
    final = draft = 0.0
    total_secs = 0
    print(f"{'shot':<8}{'model':<26}{'sec':>4}{'final$':>9}{'draft$':>9}")
    for s in shots:
        fin = s["seconds"] * rate_for(s["model"], s.get("resolution", fres), s["seconds"], s.get("audio", audio)) / (1 - f)
        dr = 0.0 if skip else min(a.draft_seconds, s["seconds"]) * rate_for(s["model"], "480p", min(a.draft_seconds, s["seconds"]), s.get("audio", audio)) * a.draft_rounds
        final += fin; draft += dr; total_secs += s["seconds"]
        print(f"{s['id']:<8}{s['model']:<26}{s['seconds']:>4}{fin:>9.2f}{dr:>9.2f}")
    stills = a.stills
    if stills is None:
        imgs = read_json(pdir / "images.json", {"images": []})["images"]
        irate = rates().get("image_models", {}).get(IMAGE_MODEL, 0.04)
        stills = round(sum(1 for i in imgs if not (pdir / i["out"]).exists()) * irate, 2)
    total = final + draft + stills
    budget = {"final": round(final, 2), "drafts": round(draft, 2), "stills": stills, "estimate": round(total, 2),
              "stop_loss": round(total * STOP_LOSS, 2), "failure_rate": f, "draft_rounds": a.draft_rounds,
              "footage_seconds": total_secs, "final_resolution": fres, "skip_draft": skip, "created": datetime.now().isoformat(timespec="seconds"), "approved": False}
    write_json(pdir / "budget.json", budget)
    print(f"\nFinal resolution: {fres}{' (drafts skipped)' if skip else ''}\nFootage: {total_secs}s | finals ${final:.2f} + drafts ${draft:.2f} + stills ${stills:.2f}")
    print(f"ESTIMATE ${total:.2f}   STOP-LOSS ${total * STOP_LOSS:.2f}")
    print(f"Approve with: python3 vidad.py approve {a.project} budget")


def cmd_approve(a):
    pdir = project_dir(a.project)
    if a.shot == "budget":
        b = read_json(pdir / "budget.json") or sys.exit("Run estimate first.")
        b["approved"] = True
        write_json(pdir / "budget.json", b)
        return print(f"Budget approved: ${b['estimate']:.2f}")
    if a.kind not in ("draft", "final"):
        sys.exit("Usage: approve <project> <shot> draft|final")
    d = read_json(pdir / "shots.json")
    shot = next((s for s in d["shots"] if s["id"] == a.shot), None) or sys.exit("Unknown shot.")
    shot[f"{a.kind}_ok"] = True
    done = [r for r in read_log(pdir) if r["shot"] == a.shot and r["stage"] == a.kind and r["result"] == "completed"]
    if done:
        shot[f"{a.kind}_clip"] = f"clips/{a.shot}_{a.kind}_a{done[-1]['attempt']}.mp4"
    write_json(pdir / "shots.json", d)
    print(f"{a.shot}: {a.kind} approved.")


def to_url(ref, pdir):
    if ref.startswith("http"):
        return ref
    path = (pdir / ref)
    if not path.exists():
        sys.exit(f"Still not found: {path}")
    mime = mimetypes.guess_type(path)[0] or "image/png"
    return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode()


def extract_last_frame(video, out):
    """Save the last frame of `video` as PNG. Uses ffmpeg if present, else the macOS Swift helper."""
    out.parent.mkdir(parents=True, exist_ok=True)
    if shutil.which("ffmpeg"):
        cmd = ["ffmpeg", "-y", "-loglevel", "error", "-sseof", "-0.1", "-i", str(video), "-frames:v", "1", str(out)]
    elif sys.platform == "darwin" and shutil.which("swift"):
        cmd = ["swift", str(HERE / "tools" / "lastframe.swift"), str(video), str(out)]
    else:
        sys.exit("Need ffmpeg (or macOS with swift) to extract a last frame.")
    if subprocess.run(cmd, capture_output=True).returncode != 0 or not out.exists():
        sys.exit(f"Could not extract the last frame of {video}")
    return out


def last_frame_of(pdir, src, need_approved=True):
    """Latest completed final clip of shot `src` -> stills/last_frames/<src>.png (relative path)."""
    shots = read_json(pdir / "shots.json")["shots"]
    s = next((x for x in shots if x["id"] == src), None) or sys.exit(f"continue_from: unknown shot {src}")
    if need_approved and not s.get("final_ok"):
        sys.exit(f"GATE: {src} is not approved, so {src}'s last frame will not be used. Watch it, then: approve <project> {src} final")
    rows = [r for r in read_log(pdir) if r["shot"] == src and r["stage"] == "final" and r["result"] == "completed"]
    if not rows:
        sys.exit(f"continue_from: {src} has no completed final clip yet.")
    clip = pdir / "clips" / f"{src}_final_a{rows[-1]['attempt']}.mp4"
    if not clip.exists():
        sys.exit(f"continue_from: clip not found: {clip}")
    extract_last_frame(clip, pdir / "stills" / "last_frames" / f"{src}.png")
    return f"stills/last_frames/{src}.png"


def cmd_run(a):
    pdir = project_dir(a.project)
    budget = read_json(pdir / "budget.json") or sys.exit("GATE: no budget. Run estimate first.")
    if not budget["approved"]:
        sys.exit(f"GATE: budget not approved. Run: python3 vidad.py approve {a.project} budget")
    d = read_json(pdir / "shots.json")
    shot = next((s for s in d["shots"] if s["id"] == a.shot), None) or sys.exit("Unknown shot id.")
    log = [r for r in read_log(pdir) if r["shot"] == a.shot]
    if a.stage == "final":
        if not shot.get("draft_ok") and not d.get("skip_draft"):
            sys.exit("GATE: draft not approved. Review the draft, then: approve <project> <shot> draft")
        finals = [r for r in log if r["stage"] == "final"]
        if len(finals) >= 1 + MAX_FINAL_RETRIES and not a.override:
            sys.exit(f"GATE: {len(finals)} final attempts already (max {1 + MAX_FINAL_RETRIES}). "
                     "Change the prompt/approach, edit shots.json, and use --override to reset your mind, not your wallet.")
    res = "480p" if a.stage == "draft" else shot.get("resolution", d.get("final_resolution", "720p"))
    secs = min(a.draft_seconds, shot["seconds"]) if a.stage == "draft" else shot["seconds"]
    audio = shot.get("audio", d.get("audio", False))
    planned = secs * rate_for(shot["model"], res, secs, audio)
    if spent(pdir) + planned > budget["stop_loss"] and not a.override:
        sys.exit(f"STOP-LOSS: spent ${spent(pdir):.2f} + this ${planned:.2f} exceeds ${budget['stop_loss']:.2f} "
                 "(130% of estimate). Re-approve: re-run estimate, or pass --override.")
    body = {"model": shot["model"], "prompt": shot["prompt"], "duration": secs, "resolution": res,
            "aspect_ratio": d.get("aspect_ratio", "16:9"), "generate_audio": audio}
    first = shot.get("first_frame")
    if shot.get("continue_from"):
        first = last_frame_of(pdir, shot["continue_from"])
        print(f"Continuing from {shot['continue_from']}: first frame = its last frame ({first})")
    frames = []
    if first:
        frames.append({"type": "image_url", "image_url": {"url": to_url(first, pdir)}, "frame_type": "first_frame"})
    if shot.get("last_frame"):
        frames.append({"type": "image_url", "image_url": {"url": to_url(shot["last_frame"], pdir)}, "frame_type": "last_frame"})
    if frames:
        body["frame_images"] = frames
    shown = json.dumps({k: (v if k != "frame_images" else [f"[{f['frame_type']} image]" for f in v]) for k, v in body.items()},
                       indent=2, ensure_ascii=False)
    print(f"{a.shot} [{a.stage}] est. cost ${planned:.2f}\n{shown}")
    if a.dry_run:
        return print("\nDRY RUN - nothing submitted, nothing spent.")
    key = load_env()
    info = {m["id"]: m for m in (lambda r: r.get("data", r))(call("GET", "/videos/models", key))}.get(shot["model"])
    if info:
        if res not in (info.get("supported_resolutions") or [res]):
            sys.exit(f"{shot['model']} does not support {res}: {info.get('supported_resolutions')}")
        if secs not in (info.get("supported_durations") or [secs]):
            sys.exit(f"{shot['model']} does not support {secs}s: {info.get('supported_durations')}")
        need = {f["frame_type"] for f in frames}
        if need - set(info.get("supported_frame_images") or need):
            sys.exit(f"{shot['model']} does not support frames {sorted(need)}: {info.get('supported_frame_images')}")
    job = call("POST", "/videos", key, body)
    jid = job["id"]
    print(f"Submitted job {jid}. Polling every 10s (Ctrl+C is safe; job keeps running, check status later).")
    status, poll, t0 = job.get("status"), job, time.time()
    attempt = len([r for r in log if r["stage"] == a.stage]) + 1
    try:
        while status not in ("completed", "failed"):
            if time.time() - t0 > 1500:
                status = "timeout"
                break
            time.sleep(10)
            poll = call("GET", f"/videos/{jid}", key)
            status = poll.get("status")
            print(f"  {status} ({int(time.time() - t0)}s)")
    except KeyboardInterrupt:
        status = "interrupted"
    if status in ("timeout", "interrupted"):
        # Job may still bill. Log the planned cost as a conservative placeholder so stop-loss counts it;
        # `sync` replaces it with the real cost and downloads the clip if it finished.
        append_log(pdir, {"timestamp": datetime.now().isoformat(timespec="seconds"), "shot": a.shot, "stage": a.stage,
                          "model": shot["model"], "resolution": res, "seconds": secs, "attempt": attempt, "job_id": jid,
                          "cost": round(planned, 6), "result": status})
        sys.exit(f"{status.upper()}: job {jid} not finished. Logged at planned ${planned:.2f}. "
                 f"Later run: python3 vidad.py sync {a.project}")
    cost = (poll.get("usage") or {}).get("cost") or 0
    out = ""
    if status == "completed":
        out = str(pdir / "clips" / f"{a.shot}_{a.stage}_a{attempt}.mp4")
        Path(out).write_bytes(call("GET", f"/videos/{jid}/content?index=0", key, raw=True))
    else:
        print("FAILED:", poll.get("error") or poll)
    append_log(pdir, {"timestamp": datetime.now().isoformat(timespec="seconds"), "shot": a.shot, "stage": a.stage,
                      "model": shot["model"], "resolution": res, "seconds": secs, "attempt": attempt, "job_id": jid,
                      "cost": cost, "result": status})
    print(f"{status.upper()}  cost ${float(cost):.3f}  total spent ${spent(pdir):.2f} / est ${budget['estimate']:.2f}")
    if out:
        print(f"Saved {out}\nWatch it, then: python3 vidad.py approve {a.project} {a.shot} {a.stage}")


def cmd_sync(a):
    """Resolve logged jobs left as timeout/interrupted: fetch real status + cost, download finished clips."""
    pdir = project_dir(a.project)
    rows = read_log(pdir)
    todo = [r for r in rows if r["result"] not in ("completed", "failed")]
    if not todo:
        return print("Nothing to sync.")
    key = load_env()
    for r in todo:
        poll = call("GET", f"/videos/{r['job_id']}", key)
        st = poll.get("status")
        print(f"{r['shot']} {r['stage']} a{r['attempt']} {r['job_id']}: {st}")
        if st not in ("completed", "failed"):
            continue
        r["result"], r["cost"] = st, (poll.get("usage") or {}).get("cost") or 0
        if st == "completed":
            out = pdir / "clips" / f"{r['shot']}_{r['stage']}_a{r['attempt']}.mp4"
            out.write_bytes(call("GET", f"/videos/{r['job_id']}/content?index=0", key, raw=True))
            print(f"  saved {out}")
    with (pdir / "cost_log.csv").open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=LOG_COLS)
        w.writeheader(); w.writerows(rows)
    print(f"Total spent ${spent(pdir):.2f}")


def cmd_lastframe(a):
    pdir = project_dir(a.project)
    print("Saved", HERE / "projects" / a.project / last_frame_of(pdir, a.shot, need_approved=False))


def sniff_ext(data):
    return ".jpg" if data[:3] == b"\xff\xd8\xff" else ".png"


def cmd_image(a):
    """Generate one still listed in images.json with Qwen Image 3 via OpenRouter /images (references as objects)."""
    pdir = project_dir(a.project)
    budget = read_json(pdir / "budget.json") or sys.exit("GATE: no budget. Run estimate first.")
    if not budget["approved"]:
        sys.exit(f"GATE: budget not approved. Run: python3 vidad.py approve {a.project} budget")
    spec = read_json(pdir / "images.json") or sys.exit("No images.json in this project.")
    by_id = {i["id"]: i for i in spec["images"]}
    img = by_id.get(a.id) or sys.exit(f"Unknown image id. Known: {', '.join(by_id)}")
    refs = []
    for r in img.get("refs", []):
        path = pdir / (by_id[r]["out"] if r in by_id else r)
        if not path.exists():
            sys.exit(f"Reference not found: {path} (generate or add it first)")
        refs.append(path)
    if len(refs) > 4:
        sys.exit("Qwen Image 3 accepts at most 4 reference images.")
    prompt = (spec.get("style", "") + " " + img["prompt"]).strip()
    planned = rates().get("image_models", {}).get(IMAGE_MODEL, 0.04)
    if spent(pdir) + planned > budget["stop_loss"] and not a.override:
        sys.exit(f"STOP-LOSS: spent ${spent(pdir):.2f} + ${planned:.2f} exceeds ${budget['stop_loss']:.2f}.")
    body = {"model": IMAGE_MODEL, "prompt": prompt, "aspect_ratio": img.get("aspect_ratio", "9:16"), "resolution": "2K", "n": 1,
            "input_references": [{"type": "image_url", "image_url": {"url": "data:image/png;base64," + base64.b64encode(p.read_bytes()).decode()}}
                                 for p in refs]}
    shown = {k: (v if k != "input_references" else [p.name for p in refs]) for k, v in body.items()}
    print(f"{a.id} [image] est. cost ${planned:.3f}\n{json.dumps(shown, indent=2, ensure_ascii=False)}")
    if a.dry_run:
        return print("\nDRY RUN - nothing submitted, nothing spent.")
    out = pdir / img["out"]
    if out.exists():
        sys.exit(f"{out} already exists. `discard` it first (keeps the cost record), then regenerate.")
    r = call("POST", "/images", load_env(), body)
    data = base64.b64decode((r.get("data") or [{}])[0].get("b64_json") or sys.exit(f"No image in response: {str(r)[:300]}"))
    out = out.with_suffix(sniff_ext(data))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(data)
    cost = (r.get("usage") or {}).get("cost") or 0
    attempt = len([x for x in read_log(pdir) if x["shot"] == a.id and x["stage"] == "image"]) + 1
    append_log(pdir, {"timestamp": datetime.now().isoformat(timespec="seconds"), "shot": a.id, "stage": "image", "model": IMAGE_MODEL,
                      "resolution": "2K", "seconds": 0, "attempt": attempt, "job_id": "", "cost": cost, "result": "completed"})
    print(f"Saved {out}  cost ${float(cost):.3f}  total spent ${spent(pdir):.2f} / est ${budget['estimate']:.2f}")


def cmd_check(a):
    """Save frames spread across the WHOLE clip so you can look for extra people, stray text and broken endings."""
    pdir = project_dir(a.project)
    d = read_json(pdir / "shots.json")
    shot = next((s for s in d["shots"] if s["id"] == a.shot), None) or sys.exit("Unknown shot id.")
    rows = [r for r in read_log(pdir) if r["shot"] == a.shot and r["stage"] == "final" and r["result"] == "completed"]
    if not rows:
        sys.exit(f"{a.shot} has no completed final clip.")
    clip = pdir / "clips" / f"{a.shot}_final_a{rows[-1]['attempt']}.mp4"
    out = pdir / "checks" / clip.stem
    out.mkdir(parents=True, exist_ok=True)
    if shutil.which("ffmpeg"):
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(clip), "-vf", f"fps={a.frames}/{max(shot['seconds'], 1)}",
                        str(out / "f%02d.png")], check=False)
    elif sys.platform == "darwin" and shutil.which("swift"):
        subprocess.run(["swift", str(HERE / "tools" / "frames.swift"), str(clip), str(out), str(a.frames)], check=False,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        sys.exit("Need ffmpeg (or macOS with swift) to extract frames.")
    print(f"Frames of {clip.name} in {out}\nLook at EVERY frame: extra people, garbled text, logos, a broken ending.")
    for f in sorted(out.glob("*.png")):
        print("  ", f)


def cost_of(pdir, name):
    """Cost of the job that made a file named like s01_final_a2.mp4 or an image id (best effort)."""
    stem = Path(name).stem
    parts = stem.split("_")
    log = read_log(pdir)
    if len(parts) >= 3 and parts[-1].startswith("a") and parts[-1][1:].isdigit():
        shot, stage, att = "_".join(parts[:-2]), parts[-2], parts[-1][1:]
        for r in log:
            if r["shot"] == shot and r["stage"] == stage and r["attempt"] == att:
                return float(r["cost"] or 0)
    imgs = [r for r in log if r["stage"] == "image" and r["shot"] == stem]
    return float(imgs[-1]["cost"] or 0) if imgs else 0.0


def cmd_discard(a):
    """Move a clip or still to a _discarded folder next to it (never deletes) and record why and what it cost."""
    pdir = project_dir(a.project)
    src = (pdir / a.file) if (pdir / a.file).exists() else next((pdir / f for f in ("clips/" + a.file, "stills/" + a.file) if (pdir / f).exists()), None)
    if not src:
        sys.exit(f"File not found in {pdir}: {a.file}")
    cost = cost_of(pdir, src.name)
    dest_dir = src.parent / "_discarded"
    dest_dir.mkdir(exist_ok=True)
    dest = dest_dir / src.name
    shutil.move(str(src), str(dest))
    rec = read_json(pdir / "discarded.json", [])
    rec.append({"file": str(dest.relative_to(pdir)), "cost": cost, "reason": a.message or "", "when": datetime.now().isoformat(timespec="seconds")})
    write_json(pdir / "discarded.json", rec)
    print(f"Moved to {dest.relative_to(pdir)} (cost ${cost:.3f} now counted as discarded). Reason: {a.message or '-'}")


def cmd_costs(a):
    pdir = project_dir(a.project)
    rows = read_log(pdir)
    disc = read_json(pdir / "discarded.json", [])
    disc_names = {Path(x["file"]).name for x in disc}
    def fname(r):
        return f"{r['shot']}_{r['stage']}_a{r['attempt']}.mp4"
    used, waste = [], []
    for r in rows:
        (waste if (fname(r) in disc_names or (r["stage"] == "image" and any(Path(x["file"]).stem == r["shot"] for x in disc))) else used).append(r)
    def line(r):
        return f"  {r['shot']:<8}{r['stage']:<7}a{r['attempt']:<3}{r['model'].split('/')[-1]:<18}{r['resolution']:<6}{r['seconds']}s  ${float(r['cost'] or 0):.3f}"
    tu = sum(float(r["cost"] or 0) for r in used); tw = sum(float(r["cost"] or 0) for r in waste)
    print("USED"); [print(line(r)) for r in used]; print(f"  total USED      ${tu:.3f}")
    print("\nDISCARDED (moved to _discarded)"); [print(line(r)) for r in waste]
    for x in disc:
        print(f"  {x['file']}  ${x['cost']:.3f}  - {x['reason']}")
    print(f"  total DISCARDED ${tw:.3f}")
    b = read_json(pdir / "budget.json") or {}
    print(f"\nALL ${tu + tw:.3f}" + (f"   budget estimate ${b['estimate']:.2f}, stop-loss ${b['stop_loss']:.2f}" if b else ""))


def cmd_status(a):
    pdir = project_dir(a.project)
    d = read_json(pdir / "shots.json")
    b = read_json(pdir / "budget.json") or {}
    log = read_log(pdir)
    print(f"{'shot':<8}{'draft':<8}{'final':<8}{'attempts(d/f)':<15}{'spent$':>8}")
    for s in d["shots"]:
        r = [x for x in log if x["shot"] == s["id"]]
        dn = len([x for x in r if x["stage"] == "draft"]); fn = len([x for x in r if x["stage"] == "final"])
        print(f"{s['id']:<8}{'OK' if s.get('draft_ok') else '-':<8}{'OK' if s.get('final_ok') else '-':<8}"
              f"{f'{dn}/{fn}':<15}{sum(float(x['cost'] or 0) for x in r):>8.2f}")
    if b:
        pct = spent(pdir) / b["estimate"] * 100 if b["estimate"] else 0
        print(f"\nSpent ${spent(pdir):.2f} of ${b['estimate']:.2f} estimate ({pct:.0f}%), stop-loss ${b['stop_loss']:.2f}")


def cmd_report(a):
    pdir = project_dir(a.project)
    b = read_json(pdir / "budget.json") or {}
    log = read_log(pdir)
    finals = [r for r in log if r["stage"] == "final"]
    good = [r for r in finals if r["result"] == "completed"]
    kept = len([s for s in read_json(pdir / "shots.json")["shots"] if s.get("final_ok")])
    print(f"Actual ${spent(pdir):.2f} vs estimate ${b.get('estimate', 0):.2f}")
    if finals:
        print(f"Final attempts: {len(finals)}, kept shots: {kept} -> measured failure rate "
              f"{(1 - kept / len(finals)) * 100:.0f}% (you assumed {b.get('failure_rate', 0) * 100:.0f}%)")
    print("Update --failure in your next estimate with this number after ~5 videos. Reconcile with openrouter.ai/activity.")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = p.add_subparsers(dest="cmd", required=True)
    sp.add_parser("models").set_defaults(fn=cmd_models)
    x = sp.add_parser("new"); x.add_argument("project"); x.set_defaults(fn=cmd_new)
    x = sp.add_parser("estimate"); x.add_argument("project")
    x.add_argument("--failure", type=float, default=0.4); x.add_argument("--draft-rounds", type=int, default=2)
    x.add_argument("--stills", type=float, default=None); x.add_argument("--draft-seconds", type=int, default=4)
    x.set_defaults(fn=cmd_estimate)
    x = sp.add_parser("approve"); x.add_argument("project"); x.add_argument("shot")
    x.add_argument("kind", nargs="?"); x.set_defaults(fn=cmd_approve)
    x = sp.add_parser("run"); x.add_argument("project"); x.add_argument("shot")
    x.add_argument("--stage", choices=["draft", "final"], required=True); x.add_argument("--draft-seconds", type=int, default=4)
    x.add_argument("--dry-run", action="store_true"); x.add_argument("--override", action="store_true")
    x.set_defaults(fn=cmd_run)
    x = sp.add_parser("image"); x.add_argument("project"); x.add_argument("id"); x.add_argument("--dry-run", action="store_true")
    x.add_argument("--override", action="store_true"); x.set_defaults(fn=cmd_image)
    x = sp.add_parser("check"); x.add_argument("project"); x.add_argument("shot"); x.add_argument("--frames", type=int, default=8); x.set_defaults(fn=cmd_check)
    x = sp.add_parser("discard"); x.add_argument("project"); x.add_argument("file"); x.add_argument("-m", "--message", default=""); x.set_defaults(fn=cmd_discard)
    x = sp.add_parser("costs"); x.add_argument("project"); x.set_defaults(fn=cmd_costs)
    x = sp.add_parser("lastframe"); x.add_argument("project"); x.add_argument("shot"); x.set_defaults(fn=cmd_lastframe)
    for n, f in (("status", cmd_status), ("report", cmd_report), ("sync", cmd_sync)):
        x = sp.add_parser(n); x.add_argument("project"); x.set_defaults(fn=f)
    a = p.parse_args(); a.fn(a)


if __name__ == "__main__":
    main()
