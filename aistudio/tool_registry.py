"""The single tool table: MCP, the studio crew and the HTTP API docs all read it.

Each entry is (description, JSON input schema, handler) exactly as MCP serves it, plus crew metadata in META below:
  cost_class  free | paid | approval | human_only
  agents      allow-list default: "*" = any crew agent whose definition lists the tool
  writes      True when the tool changes the project (assist mode only proposes these as diffs)

Crew rule (hard-coded, tested): tools of class approval or human_only are NEVER available to a crew agent, whatever an agent
definition, an override file or the `agents` field says.  They stay exactly as before for MCP and HTTP (server/api_docs.py
agent_allowed is still the HTTP authority).  'paid' tools never execute for the crew: they become proposals for a human.
"""
from aistudio import jobs
from aistudio.domain.common import ServiceError

S = lambda **props: {"type": "object", "properties": props, "required": [k for k, v in props.items() if not v.get("optional")]}
STR = {"type": "string"}
CLASSES = ("free", "paid", "approval", "human_only")


def _m():
    from aistudio import mcp_server   # lazy: the approval helpers live there (and tests patch them there)
    return mcp_server


def _late(name):
    return lambda ws, a: getattr(_m(), name)(ws, a)


def _no_job(jid):
    raise ServiceError(f"unknown job {jid}")


TOOLS = {
    "list_projects": ("List projects with spend and budget status.", S(), lambda ws, a: ws.list_projects()),
    "create_project": ("Create a project folder from the guided templates.", S(name=STR), lambda ws, a: {"name": ws.create_project(a["name"])}),
    "delete_project": (
        "Move a project to _trash (restorable). Discard or delete a project folder. Requires human confirmation parameter matching project name or 'yes'.",
        S(name=STR, confirm=STR),
        lambda ws, a: ws.delete_project(a["name"], a["confirm"]),
    ),
    "get_project": ("Overview: shots, images, budget, costs (used vs discarded), proposals, files, reviews.", S(name=STR), lambda ws, a: ws.overview(a["name"])),
    "read_doc": ("Read Story.md, brief.md or TODO.md.", S(name=STR, doc={"type": "string", "enum": ["Story.md", "brief.md", "TODO.md"]}), lambda ws, a: {"text": ws.get_text(a["name"], a["doc"])}),
    "write_doc": ("Write Story.md, brief.md or TODO.md (plain text). Free.", S(name=STR, doc={"type": "string", "enum": ["Story.md", "brief.md", "TODO.md"]}, text=STR), lambda ws, a: ws.put_text(a["name"], a["doc"], a["text"]) or {"ok": True}),
    "get_brief": ("The brief: every field, its value, and which required fields are still missing.", S(name=STR), lambda ws, a: ws.brief_get(a["name"])),
    "update_brief": ("Fill brief fields (free). Keys: brand, goal, story, audience, platform, length_seconds, language, characters, setting, cta, brand_assets, claims_to_avoid, budget_cap.", S(name=STR, fields={"type": "object"}), lambda ws, a: ws.brief_put(a["name"], a["fields"])),
    "get_model_setup": ("Read-only: which AI providers are connected (state only, never keys) and which models each role (chat, verify, vision, image, video) tries, in fallback order. Agents cannot change this or read keys.", S(),
                        lambda ws, a: {"providers": [{"id": p["id"], "label": p["label"], "type": p["type"], "state": p["status"]["state"]} for p in ws.providers_list()["providers"]],
                                       "roles": {r: [f"{c['provider']}:{c['model']}" for c in v["chain"]] for r, v in ws.roles_get()["roles"].items()}}),
    "get_todos": ("Automatic progress steps plus the manual TODO list.", S(name=STR), lambda ws, a: ws.todos(a["name"])),
    "get_verification": ("Verification of brief, story, assets, shots and todos: rule findings (always fresh) plus the latest AI review. Free.", S(name=STR), lambda ws, a: ws.verify_status(a["name"])),
    "rename_asset": ("Rename an image asset id everywhere (files, references, cost log). Free.", S(name=STR, old=STR, new=STR), lambda ws, a: ws.rename_asset(a["name"], a["old"], a["new"])["images"]),
    "rename_shot": ("Rename a shot id everywhere (clips, cost log, discarded history). Free.", S(name=STR, old=STR, new=STR), lambda ws, a: ws.rename_shot(a["name"], a["old"], a["new"])["shots"]),
    "convert_story": ("Parse Story.md and write shots.json + images.json. Free. Overwrites both.", S(name=STR), lambda ws, a: ws.convert_story(a["name"])),
    "update_shots": ("Replace shots.json (validated). Free. Changing shots needs a new estimate and human re-approval.", S(name=STR, doc={"type": "object"}), lambda ws, a: ws.put_shots(a["name"], a["doc"]) or {"ok": True}),
    "update_images": ("Replace images.json (validated). Free.", S(name=STR, doc={"type": "object"}), lambda ws, a: ws.put_images(a["name"], a["doc"]) or {"ok": True}),
    "estimate": ("Compute budget estimate (free). A human must approve it through MCP elicitation or the one-time fallback code before generating.", S(name=STR, failure={"type": "number", "optional": True}), lambda ws, a: _m()._estimate_mcp(ws, a)),
    "approve_budget": (
        "Request human approval for the exact estimated budget. MCP elicitation is used when the client advertises it; otherwise a one-time code challenge is returned. confirm=true is not accepted.",
        S(name=STR, code={"type": "string", "optional": True}, code_id={"type": "string", "optional": True}),
        lambda ws, a: _m()._approve_budget_mcp(ws, a),
    ),
    "propose": ("Propose a PAID action (nothing is spent). kind = image | clip | review; target = image id or shot id. A human must approve the exact proposal before it can run.",
                S(name=STR, kind={"type": "string", "enum": ["image", "clip", "review"]}, target=STR), lambda ws, a: _m()._propose_mcp(ws, a)),
    "get_proposal": ("Status of a proposal: pending | approved | used | rejected | expired | void.", S(name=STR, id=STR), lambda ws, a: ws.proposal_status(a["name"], a["id"])),
    "approve_proposal": (
        "Request human approval for a pending proposal. Uses MCP elicitation when available; otherwise returns a one-time code challenge. confirm=true is not accepted.",
        S(name=STR, id=STR, code={"type": "string", "optional": True}, code_id={"type": "string", "optional": True}),
        lambda ws, a: _m()._approve_proposal_mcp(ws, a),
    ),
    "reject_proposal": (
        "Reject and cancel a pending proposal.",
        S(name=STR, id=STR),
        lambda ws, a: ws.reject(a["name"], a["id"]) or {"ok": True, "rejected": a["id"]},
    ),
    "run_proposal": (
        "Execute a proposal only after human approval. Pending proposals use MCP elicitation or a one-time code challenge; confirm=true and override=true are not accepted from agents.",
        S(name=STR, id=STR, code={"type": "string", "optional": True}, code_id={"type": "string", "optional": True}),
        lambda ws, a: _m()._run_proposal_mcp(ws, a),
    ),
    "set_max_attempts": (
        "Human-only attempt limit setting. Agents cannot change generation attempt limits; use the web page or a human session.",
        S(name=STR, max_attempts={"type": "integer", "description": "Maximum attempts allowed per shot"}),
        _late("_human_only_attempt_limit"),
    ),
    "approve_shot": (
        "Human-only clip decision. Agents may inspect clips but cannot approve them through MCP; use the web page or a human session.",
        S(name=STR, shot_id=STR),
        _late("_human_only_shot_approval"),
    ),
    "list_jobs": ("Jobs in the durable job ledger (generation, exports, batches) with their state: queued, running, provider_pending, completed, failed, cancelled or needs_sync. Read-only.",
                  S(name={"type": "string", "optional": True}, state={"type": "string", "optional": True}),
                  lambda ws, a: {"jobs": jobs.list_jobs(ws.root, a.get("name") or None, a.get("state") or None)}),
    "get_job": ("One job from the ledger by id. Read-only; cancelling is human-only (web page).", S(id=STR), lambda ws, a: jobs.get(ws.root, a["id"]) or _no_job(a["id"])),
    "get_spec": ("Read-only preview of one generation: the model, seconds, frames, references, capability profile, price and warnings. kind = image | clip | image_edit | clip_extend.",
                 S(name=STR, kind={"type": "string", "enum": ["image", "clip", "image_edit", "clip_extend"]}, target=STR), lambda ws, a: ws.spec(a["name"], a["kind"], a["target"])),
    "get_costs": ("Cost log, used vs discarded split, budget.", S(name=STR), lambda ws, a: ws.costs(a["name"])),
    "discard": ("Move a clip/still to _discarded (never deletes) with a reason.", S(name=STR, rel=STR, reason={"type": "string", "optional": True}), lambda ws, a: ws.discard(a["name"], a["rel"], a.get("reason", ""))),
    "restore": ("Restore a discarded file.", S(name=STR, rel=STR), lambda ws, a: {"file": ws.restore(a["name"], a["rel"])}),
    "list_providers": ("Connected AI providers (id, label, type, status). There is no app-wide mode: each project is a test project or a real one.", S(), lambda ws, a: {"providers": [{k: v for k, v in p.items() if k in ("id", "label", "type", "enabled", "status")} for p in ws.providers_list()["providers"] if p["type"] != "fake"]}),
    "production_progress": ("Get production checklist groups, queue items, and next action.", S(name=STR), lambda ws, a: ws.production_progress(a["name"])),
    "generate_all_plan": ("Freeze the plan for everything left to generate as a batch (exact prices; nothing is spent or approved). Returns a batch id; a human must approve it with approve_batch.", S(name=STR), lambda ws, a: ws.batches.create(a["name"], actor="mcp")),
    "get_batch": ("Status of a batch and each of its items.", S(name=STR, id=STR), lambda ws, a: ws.batches.get(a["name"], a["id"])),
    "approve_batch": (
        "Request human approval for the exact batch total. Uses MCP elicitation when available; otherwise returns a one-time code challenge. confirm=true is not accepted.",
        S(name=STR, id=STR, code={"type": "string", "optional": True}, code_id={"type": "string", "optional": True}),
        lambda ws, a: _m()._approve_batch_mcp(ws, a),
    ),
    "run_batch": ("Run a batch a human already approved, item by item; stops at the first problem or changed item (needs_reapproval).", S(name=STR, id=STR), _late("_run_batch_mcp")),
    "get_edit": ("Get timeline video edit structure (edit.json) and tool status.", S(name=STR), lambda ws, a: ws.edit_get(a["name"])),
    "update_edit": ("Update timeline video edit structure (edit.json). Free.", S(name=STR, doc={"type": "object"}), lambda ws, a: ws.edit_put(a["name"], a["doc"]) or {"ok": True}),
    "export_edit": (
        "Render / export the timeline edited video (edit.json) into a final video file.",
        S(name=STR),
        lambda ws, a: ws.edit_export(a["name"]),
    ),
    "unregistered_stills": ("Find unregistered images in the stills folder that can be added to project assets.", S(name=STR), lambda ws, a: ws.unregistered_stills(a["name"])),
    "import_stills": ("Import unregistered stills into project assets (images.json). Free.", S(name=STR, items={"type": "array"}), lambda ws, a: ws.import_stills(a["name"], a["items"])),
    "upload_image": (
        "Upload or import an image file (from a local file path or base64 string) into project assets (stills/ and images.json). Free.",
        S(
            name=STR,
            path={"type": "string", "optional": True, "description": "Local filesystem path to the image file"},
            data={"type": "string", "optional": True, "description": "Base64-encoded image string or data URL"},
            id={"type": "string", "optional": True, "description": "Asset ID (e.g. hero, logo, s01)"},
            kind={"type": "string", "enum": ["character", "background", "frame", "other"], "optional": True, "description": "Asset category"},
            replace={"type": "boolean", "optional": True, "description": "Replace existing still with same id (old one moved to Discarded)"},
            prompt={"type": "string", "optional": True, "description": "Asset description or prompt for images.json"},
        ),
        lambda ws, a: ws.upload_image(
            a["name"],
            aid=a.get("id"),
            path=a.get("path"),
            data=a.get("data"),
            kind=a.get("kind"),
            replace=bool(a.get("replace", False)),
            prompt=a.get("prompt", ""),
        ),
    ),
    "analyze_character": ("Propose a paid multi-angle consistency review on a character asset image. Nothing is spent; a human must approve the returned review proposal before it can run.", S(name=STR, rel=STR), lambda ws, a: ws.analyze_character_image(a["name"], a["rel"])),
    "add_todo": ("Add a task to the project TODO list.", S(name=STR, title=STR), lambda ws, a: ws.todo_add(a["name"], a["title"])),
    "toggle_todo": ("Toggle task completion status on the project TODO list.", S(name=STR, tid=STR), lambda ws, a: ws.todo_toggle(a["name"], a["tid"])),
    "remove_todo": (
        "Remove a task from the project TODO list.",
        S(name=STR, tid=STR),
        lambda ws, a: ws.todo_remove(a["name"], a["tid"]) or {"ok": True, "removed": a["tid"]},
    ),
    "list_trash": ("List deleted projects available in trash for restoration.", S(), lambda ws, a: ws.trash_list()),
    "restore_trash": ("Restore a project from trash.", S(tid=STR, as_name={"type": "string", "optional": True}), lambda ws, a: ws.trash_restore(a["tid"], as_name=a.get("as_name"))),
    "export_project": (
        "Export the project as a downloadable zip archive.",
        S(name=STR, include_discarded={"type": "boolean", "optional": True}),
        lambda ws, a: {"path": str(ws.export_project(a["name"], include_discarded=bool(a.get("include_discarded", False))))},
    ),
    "edit_still": (
        "Propose an inpaint, outpaint or background-swap edit of an existing still. Nothing is spent; a human must approve the returned proposal before execution.",
        S(name=STR, still_id=STR, prompt=STR, edit_mode={"type": "string", "enum": ["inpaint_insertion", "inpaint_removal", "outpaint", "bgswap"], "optional": True}, mask_mode={"type": "string", "optional": True}),
        lambda ws, a: ws.edit_still(a["name"], a["still_id"], a["prompt"], edit_mode=a.get("edit_mode", "inpaint_insertion"), mask_mode=a.get("mask_mode", "MASK_MODE_BACKGROUND")),
    ),
    "extend_clip": (
        "Propose extending an existing video clip forward with a continuation prompt. Nothing is spent; a human must approve the returned proposal before execution.",
        S(name=STR, clip_id=STR, prompt=STR, seconds={"type": "integer", "optional": True}),
        lambda ws, a: ws.extend_clip(a["name"], a["clip_id"], a["prompt"], seconds=int(a.get("seconds", 5))),
    ),
}


FREE_READ = ("get_project", "read_doc", "get_brief", "get_model_setup", "get_todos", "get_verification", "get_proposal", "get_spec", "get_costs",
             "list_providers", "production_progress", "get_batch", "get_edit", "unregistered_stills")
FREE_WRITE = ("write_doc", "update_brief", "rename_asset", "rename_shot", "convert_story", "update_shots", "update_images", "update_edit",
              "import_stills", "add_todo", "toggle_todo", "remove_todo", "export_edit", "export_project")
PAID = ("propose", "analyze_character", "edit_still", "extend_clip", "generate_all_plan")
# approve/execute/override/cancel/delete/budget tools, tools that reveal codes, and tools that reach outside the run's project
# (other projects, trash, local file paths, the job ledger of every project) are never crew tools.
APPROVAL = ("approve_budget", "approve_proposal", "approve_batch", "approve_shot", "run_proposal", "run_batch", "reject_proposal", "set_max_attempts",
            "estimate", "discard", "restore")
HUMAN_ONLY = ("delete_project", "create_project", "list_projects", "list_trash", "restore_trash", "upload_image", "list_jobs", "get_job")

META = {}
for _names, _cls, _w in ((FREE_READ, "free", False), (FREE_WRITE, "free", True), (PAID, "paid", False), (APPROVAL, "approval", False), (HUMAN_ONLY, "human_only", False)):
    for _n in _names:
        META[_n] = {"cost_class": _cls, "agents": "*" if _cls in ("free", "paid") else (), "writes": _w}
assert set(META) == set(TOOLS), set(META) ^ set(TOOLS)   # every tool must be classified


def cost_class(tool):
    return META[tool]["cost_class"]


def crew_tools():
    """Names a crew agent may EVER be given.  approval and human_only are excluded here, the one place that decides it."""
    return sorted(n for n, m in META.items() if m["cost_class"] in ("free", "paid") and m["agents"])


def crew_catalogue(allowed):
    """The tool list shown to one agent: [{name, description, input_schema, cost_class}], only tools the agent may use."""
    ok = set(crew_tools())
    return [{"name": n, "description": TOOLS[n][0], "input_schema": TOOLS[n][1], "cost_class": cost_class(n)} for n in allowed if n in ok]
