"""Stage runs, the run plan and checkpoints (plan 28 section 3.3).

A stage = ordered crew agents + a task each.  A stage run is ONE parent record (projects/<p>/runs/<id>.json, kind "stage_run", also the
parent ledger job) whose agent steps are ordinary crew runs (child ledger jobs, payload.parent = the parent id).  Hand-offs are project
files: every agent reads the project state.  Stages never skip prerequisites.  A stage that ends with a checkpoint stops with status
awaiting_checkpoint and a card; only a human decision (continue / stop) resumes it.  Paid work is only ever a proposal or a batch that a
human approves elsewhere - nothing here approves, runs or spends.
"""
import hashlib
import json
import re
import time

from aistudio import jobs, project_lock
from aistudio.crew import agents as crew_agents, runtime
from aistudio.domain.common import ServiceError

# paid = (image kinds proposed by the stage, whether it proposes clips)
STAGES = {
    "write_storyboard": {"label": "Write storyboard", "checkpoint": True, "paid": None, "steps": [
        ("producer", "Read the project and the brief, fill in only what the human already told us, and list open decisions as TODOs."),
        ("writer", "Write Story.md for this project from the brief: shared style, characters, backgrounds and a numbered shot list."),
        ("director", "Convert Story.md into shots.json and set durations, pacing and a model per shot using get_spec.")]},
    "cast_and_design": {"label": "Cast and design", "checkpoint": True, "paid": ({"character", "background"}, False), "steps": [
        ("image-artist", "Tune prompts for character and background images that are not made yet, then propose each one once."),
        ("casting-art-director", "Review character identities and references. Propose missing identity-sheet views only when a master image already exists.")]},
    "create_scenes": {"label": "Create scenes", "checkpoint": True, "paid": ({"frame"}, False), "steps": [
        ("scene-designer", "Design a scene frame for every shot (prompts, references, first and end frames) and propose each frame image once."),
        ("cinematographer", "Read shot and spec details, then set camera direction and end_frame using the camera presets. Preserve every other shot field.")]},
    "generate_images": {"label": "Generate images", "checkpoint": False, "paid": ({"character", "background", "frame"}, False), "steps": [
        ("image-artist", "Propose every image that is not made yet and has no open proposal, once each.")]},
    "generate_clips": {"label": "Generate clips", "checkpoint": True, "paid": (set(), True), "steps": [
        ("video-director", "Tighten the clip prompt of every shot without a clip and propose each clip once.")]},
    "sound": {"label": "Sound", "checkpoint": False, "paid": (set(), False), "steps": [
        ("sound-designer", "Write the voice, captions, music and effects plan. Propose audio work only when the brief requires it.")]},
    "assemble_edit": {"label": "Assemble edit", "checkpoint": False, "paid": None, "steps": [
        ("editor", "Assemble edit.json from the clips that exist, in shot order, with captions from the voice lines. Do not export.")]},
    "qa": {"label": "QA", "checkpoint": False, "paid": None, "steps": [
        ("qa", "Check the whole project and report what the human should fix first.")]},
    "deliver": {"label": "Deliver", "checkpoint": False, "paid": None, "steps": [
        ("delivery", "Check readiness and draft publish metadata in Story.md. Do not export, upload or publish.")]},
}
MAKE_VIDEO = list(STAGES)          # dependency order
DECISIONS = ("approve_continue", "edit_continue", "stop")
CARD_OPTIONS = [{"id": "approve_continue", "label": "Approve and continue"}, {"id": "edit_continue", "label": "Edit, then continue"}, {"id": "stop", "label": "Stop"}]
MENTION = re.compile(r"^@([a-z][a-z0-9-]{1,40})\s+(\S.*)\Z", re.S)


def expand(stages):
    """['make_video'] or a list of stage names -> validated ordered stage list."""
    if isinstance(stages, str):
        stages = [stages]
    out = []
    for s in stages or []:
        out += MAKE_VIDEO if s == "make_video" else [s]
    if not out or any(s not in STAGES for s in out) or len(set(out)) != len(out):
        raise ServiceError(f"stages must be distinct names from {sorted(STAGES)} or 'make_video'")
    return sorted(out, key=MAKE_VIDEO.index)


def parse_mention(text):
    """'@writer make shot 3 more emotional' -> ('writer', 'make shot 3 more emotional'); None when it is not an @agent message."""
    m = MENTION.match(str(text or "").strip())
    return (m.group(1), m.group(2).strip()) if m else None


# ---------------------------------------------------------------- prerequisites
def prereqs(ws, project, stage):
    """What is still missing before `stage` may run (empty list = it may run).  Stages never skip these."""
    p = ws.pdir(project)
    st = ws._production(p)
    miss = []
    if st["story"]["pending"]:
        miss.append("apply or discard the drafted storyboard first")
    if stage == "write_storyboard":
        if not (any(st["brief"].values()) or (p / "Story.md").is_file()):
            miss.append("fill in the brief first")
        return miss
    if not st["shots"]:
        miss.append("write the storyboard first (there are no shots)")
    if STAGES[stage]["paid"] and not st["budget"]["approved"]:
        miss.append("estimate and approve the budget first (a human step)")
    unmade = [a for a in st["assets"] if not a["made"]]
    if stage in ("create_scenes", "generate_images") and any(a["kind"] != "frame" for a in unmade):
        miss.append("generate the character and background images first (approve their batch)")
    if stage == "generate_clips" and unmade:
        miss.append("generate all the images first, the clips need the scene frames")
    if stage in ("sound", "deliver") and any(not s["clip"] for s in st["shots"]):
        miss.append("generate a clip for every shot first")
    if stage == "deliver":
        edit = ws.edit_get(project).get("edit") or {}
        clips = (edit.get("tracks") or {}).get("video") or []
        if not clips:
            miss.append("assemble the edit first")
    if stage == "assemble_edit" and any(not s["clip"] for s in st["shots"]):
        miss.append("generate a clip for every shot first")
    return miss


# ---------------------------------------------------------------- run plan
def build_run_plan(ws, project, stages, autonomy="copilot", checkpoints=None):
    """Everything a human must see BEFORE a run starts: per stage the agents, the prerequisites still missing, the estimated paid items
    at today's exact prices (an item is counted once, in the first stage that covers it), the checkpoints and the LLM usage cap.
    Read-only: creates nothing."""
    stages = expand(stages)
    if autonomy not in runtime.AUTONOMY:
        raise ServiceError(f"autonomy must be one of {runtime.AUTONOMY}")
    cps = dict(checkpoints) if isinstance(checkpoints, dict) else {}
    p = ws.pdir(project)
    st = ws._production(p)
    seen, rows, llm_total = set(), [], 0.0
    for stage in stages:
        S = STAGES[stage]
        items, kinds = [], S["paid"]
        if kinds:
            todo = [("image", a["id"], f"{a['kind']} image: {a['id']}") for a in st["assets"] if not a["made"] and a["kind"] in kinds[0]]
            todo += [("clip", s["id"], f"video clip: {s['id']}") for s in st["shots"] if kinds[1] and not s["clip"]]
            for kind, target, label in todo:
                if (kind, target) in seen:
                    continue
                seen.add((kind, target))
                try:
                    price, model = ws._pipeline._item_price(p, kind, target)
                except ServiceError as e:
                    items.append({"kind": kind, "target": target, "label": label, "model": "", "price": None, "error": str(e)})
                    continue
                items.append({"kind": kind, "target": target, "label": label, "model": model, "price": round(float(price), 6)})
        agent_defs = [crew_agents.load(a, ws.settings_dir) for a, _ in S["steps"]]
        usd = round(sum(a["limits"]["max_llm_usd"] for a in agent_defs), 6)
        llm_total += usd
        rows.append({"stage": stage, "label": S["label"], "agents": [{"id": a["id"], "version": a["version"]} for a in agent_defs],
                     "prerequisites_missing": prereqs(ws, project, stage), "checkpoint": bool(cps.get(stage, S["checkpoint"])),
                     "free": not kinds, "paid_items": items, "paid_total": round(sum(i["price"] or 0 for i in items), 6),
                     "unpriced": sum(1 for i in items if i["price"] is None), "llm_max_usd": usd})
    plan = {"project": project, "stages": rows, "autonomy": autonomy, "paid_total": round(sum(r["paid_total"] for r in rows), 6),
            "llm": {"max_usd": round(llm_total, 6), "ai_cap_usd": ws.ai_settings()["settings"]["ai_cap_usd"]},
            "note": "Nothing starts or is spent by running the plan: paid items become proposals and a batch that a human approves at these exact prices. "
                    "Images and clips that do not exist in the storyboard yet are not priced."}
    plan["plan_hash"] = hashlib.sha256(json.dumps({k: plan[k] for k in ("stages", "autonomy", "llm")}, sort_keys=True, default=str).encode()).hexdigest()[:16]
    return plan


# ---------------------------------------------------------------- stage runs
def _save(ws, project, rec):
    runtime._save(ws, project, rec)


def _child(ws, project, rid, agent, task, autonomy, llm, progress):
    """One agent step = one ordinary crew run, recorded as its own ledger job under the stage job."""
    job = jobs.enqueue(ws.root, project, "crew_run", actor="local", state="running", payload={"agent": agent["id"], "task": task, "autonomy": autonomy, "parent": rid})
    try:
        rec = runtime.run(ws, project, agent, task, autonomy, run_id=job["id"], llm=llm, progress=progress)
    except BaseException as e:
        jobs.finish(ws.root, job["id"], "failed" if not isinstance(e, jobs.Cancelled) else "cancelled", error=jobs.error_text(e))
        raise
    jobs.finish(ws.root, job["id"], "failed" if rec["status"] == "error" else "completed", result={"run": rec["id"], "status": rec["status"]}, error=rec["error"])
    return rec


def _card(ws, project, stage, runs):
    """The checkpoint card the human decides on: what changed (diffs), what is proposed and its exact total."""
    changes, suggested, proposals, batch = {}, [], [], None
    for r in runs:
        for c in r["changes"]:
            changes[c["doc"]] = c            # last diff of a document wins (the final state is what the human reviews)
        suggested += r["suggested_changes"]
        proposals += r["proposals"]
        batch = r["batch"] or batch
    return {"title": f"{STAGES[stage]['label']}: review before continuing", "stage": stage,
            "summary": [{"agent": r["agent"]["id"], "summary": r["summary"], "status": r["status"]} for r in runs],
            "changes": list(changes.values()), "suggested_changes": suggested, "proposals": proposals,
            "batch": batch and {k: batch.get(k) for k in ("id", "total", "status", "error", "note") if k in batch},
            "proposed_total": (batch or {}).get("total", round(sum(float(x.get("price") or 0) for x in proposals), 6)),
            "options": CARD_OPTIONS}


def _advance(ws, project, rec, llm, progress):
    """Run stages from rec['next'] until a checkpoint, a block, a failure or the end.  The record is saved after every stage."""
    stages = rec["stages"]
    try:
        while rec["next"] < len(stages):
            i, stage = rec["next"], stages[rec["next"]]
            miss = prereqs(ws, project, stage)
            if miss:
                rec["status"] = "blocked"
                rec["results"] = [r for r in rec["results"] if r["stage"] != stage] + [{"stage": stage, "status": "blocked", "blocked_by": miss, "runs": []}]
                return
            res = {"stage": stage, "status": "running", "runs": [], "summary": []}
            rec["results"] = [r for r in rec["results"] if r["stage"] != stage] + [res]
            _save(ws, project, rec)
            runs = []
            for agent_id, task in STAGES[stage]["steps"]:
                agent = crew_agents.load(agent_id, ws.settings_dir)
                scale = (i, len(stages), len(STAGES[stage]["steps"]), len(runs))
                child = _child(ws, project, rec["id"], agent, task, rec["autonomy"], llm,
                               (lambda pct, s=scale: progress(100.0 * (s[0] + (s[3] + pct / 100.0) / s[2]) / s[1])) if progress else None)
                runs.append(child)
                res["runs"].append(child["id"])
                res["summary"].append({"agent": agent_id, "summary": child["summary"], "status": child["status"]})
                rec["llm_usd"] = round(rec["llm_usd"] + child["llm_usd"], 6)
                if child["status"] != "done":
                    res["status"] = "failed"
                    rec["status"], rec["error"] = "error", f"{agent_id} ended with status {child['status']}: {child['error'] or child['summary']}"
                    return
            res["status"] = "done"
            rec["next"] = i + 1
            if rec["checkpoints"].get(stage, STAGES[stage]["checkpoint"]):
                rec["status"], res["status"], res["card"] = "awaiting_checkpoint", "awaiting_checkpoint", _card(ws, project, stage, runs)
                return
        rec["status"] = "done"
    except jobs.Cancelled:
        rec["status"] = "stopped"
    except Exception as e:
        rec["status"], rec["error"] = "error", jobs.error_text(e)
    finally:
        rec["finished"] = time.time() if rec["status"] not in ("awaiting_checkpoint", "blocked") else None
        _save(ws, project, rec)


def run_stages(ws, project, stages, autonomy="copilot", checkpoints=None, run_id=None, llm=None, progress=None):
    """Start a stage run (one stage, several, or 'make_video').  Refuses at once when the FIRST stage's prerequisites are missing.
    Returns the record; it ends done / error / stopped, or waits at a checkpoint or a block for a human."""
    stages = expand(stages)
    if autonomy not in runtime.AUTONOMY:
        raise ServiceError(f"autonomy must be one of {runtime.AUTONOMY}")
    if checkpoints is not None and (not isinstance(checkpoints, dict) or set(checkpoints) - set(STAGES) or not all(isinstance(v, bool) for v in checkpoints.values())):
        raise ServiceError("checkpoints must map stage names to true or false")
    miss = prereqs(ws, project, stages[0])
    if miss:
        raise ServiceError(f"cannot run {stages[0]}: " + "; ".join(miss))
    own_job = None
    if not run_id:
        own_job = jobs.enqueue(ws.root, project, "crew_run", actor="local", state="running", payload={"stages": stages, "autonomy": autonomy})
        run_id = own_job["id"]
    rec = {"id": run_id, "kind": "stage_run", "project": project, "stages": stages, "autonomy": autonomy, "checkpoints": checkpoints or {}, "status": "running",
           "next": 0, "results": [], "decisions": [], "started": time.time(), "finished": None, "llm_usd": 0.0, "error": ""}
    _save(ws, project, rec)
    _advance(ws, project, rec, llm, progress)
    if own_job:
        jobs.finish(ws.root, run_id, "failed" if rec["status"] == "error" else "completed", result={"run": run_id, "status": rec["status"]}, error=rec["error"])
    return rec


def continue_run(ws, project, rid, decision, note="", llm=None, progress=None):
    """A human's decision on a checkpoint (or a retry after a block).  approve_continue / edit_continue run the next stages;
    stop ends the run.  The decision is recorded in the run record."""
    if decision not in DECISIONS:
        raise ServiceError(f"decision must be one of {DECISIONS}")
    rec = runtime.get_run(ws, project, rid)
    if rec.get("kind") != "stage_run":
        raise ServiceError(f"{rid} is not a stage run")
    with project_lock.lock(ws.pdir(project)):         # two clicks must not run the next stage twice
        rec = runtime.get_run(ws, project, rid)
        if rec["status"] not in ("awaiting_checkpoint", "blocked"):
            raise ServiceError(f"this run is {rec['status']}; only a run waiting at a checkpoint or blocked can continue")
        cur = rec["results"][-1]["stage"] if rec["results"] else ""
        rec["decisions"].append({"stage": cur, "decision": decision, "note": str(note or "")[:1000], "at": time.time(), "after": rec["status"]})
        if decision == "stop":
            rec.update(status="stopped", finished=time.time())
            _save(ws, project, rec)
            return rec
        rec["status"] = "running"
        _save(ws, project, rec)
    _advance(ws, project, rec, llm, progress)
    return rec
