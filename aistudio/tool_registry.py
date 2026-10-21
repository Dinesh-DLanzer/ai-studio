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


def _runs():
    from aistudio.crew import runtime
    return runtime


def _late(name):
    return lambda ws, a: getattr(_m(), name)(ws, a)


def _list_voices(ws, provider_id):
    provider = ws.runner().providers().get(provider_id)
    if not provider:
        raise ServiceError(f"unknown provider {provider_id}")
    return ws.runner().adapter(provider).list_voices()


def _no_job(jid):
    raise ServiceError(f"unknown job {jid}")


TOOLS = {
    "list_projects": ("List projects with spend and budget status.", S(), lambda ws, a: ws.list_projects()),
    "create_project": ("Create a project folder from the guided templates, optionally from a format (aspect ratio, shot skeleton, brief) and a workspace brand kit (copied into the project). Human-only: a crew agent can never create a project.",
                       S(name=STR, format={"type": "string", "optional": True, "description": "Format id, e.g. 'instagram-reel' (see list_formats)"},
                         brand_kit={"type": "string", "optional": True, "description": "Brand kit id, e.g. 'acme'"}),
                       lambda ws, a: {"name": ws.create_project(a["name"], format=a.get("format") or None, brand_kit=a.get("brand_kit") or None)}),
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
    "update_images": ("Replace images.json (validated). Free.", S(name=STR, doc={"type": "object"}), lambda ws, a: ws.put_images(a["name"], a["doc"], is_agent=True) or {"ok": True}),
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
    "build_identity_sheet": ("Build a character's identity sheet: a batch of image proposals for its missing views (front, three-quarter, profile, full-body, expression), conditioned on the master image. Nothing is spent or approved; a human must approve the returned batch with approve_batch.",
                             S(name=STR, character=STR, views={"type": "array", "optional": True}), lambda ws, a: ws.identity_sheet(a["name"], a["character"], a.get("views"), actor="mcp")),
    "list_recipes": ("Read-only: one-click recipes (product ad, product showcase, photo to clip, ...) with their inputs, and whether every step can run with the configured models (reasons when not). Free.",
                     S(name={"type": "string", "optional": True}), lambda ws, a: {"recipes": __import__("aistudio.recipes", fromlist=["list_recipes"]).list_recipes(ws, a.get("name") or None)}),
    "list_formats": ("Read-only: the project formats (aspect ratio, shots, seconds per shot, safe area, caption, CTA, loudness, brief, suggested models) as static catalog data. Free.",
                     S(), lambda ws, a: {"formats": __import__("aistudio.formats", fromlist=["load_formats"]).load_formats()}),
    "plan_recipe": ("Plan a recipe in a project: validates the inputs, prices every paid step and creates ONE awaiting-approval batch (nothing is approved, run or spent). A human must approve it with approve_batch at the exact total. Real-person recipes need a recorded consent.",
                    S(name=STR, recipe=STR, inputs={"type": "object"}),
                    lambda ws, a: __import__("aistudio.recipes", fromlist=["plan"]).plan(ws, a["name"], a["recipe"], a.get("inputs") or {}, actor="mcp")),
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
    "clip_tool": (
        "Propose a PAID AI clip tool on an existing clip: upscale_ai (scale 2|4), reframe_ai (aspect_ratio), restyle (prompt), replace (target object|background + prompt), "
        "motion_transfer (reference driving video + subject), character_swap (reference image + subject). Nothing is spent; a human must approve the exact price. The result is a new version "
        "beside the clip. motion_transfer and character_swap need the subject's consent recorded by a human first.",
        S(name=STR, tool={"type": "string", "enum": ["upscale_ai", "reframe_ai", "restyle", "replace", "motion_transfer", "character_swap"]}, clip_id=STR,
          prompt={"type": "string", "optional": True}, reference={"type": "string", "optional": True}, subject={"type": "string", "optional": True},
          seconds={"type": "integer", "optional": True}, scale={"type": "integer", "optional": True}, aspect_ratio={"type": "string", "optional": True},
          target={"type": "string", "optional": True}),
        lambda ws, a: ws.clip_tool(a["name"], a["tool"], a["clip_id"], **{k: v for k, v in a.items() if k not in ("name", "tool", "clip_id")}),
    ),
    "audio_tool": (
        "Propose a paid audio task (tts, music, sfx, lipsync or transcribe). Nothing is spent; a human must approve the exact request before it can run.",
        S(name=STR, task={"type": "string", "enum": ["tts", "music", "sfx", "lipsync", "transcribe"]}, target=STR,
          options={"type": "object", "optional": True}),
        lambda ws, a: ws.propose(a["name"], a["task"], a["target"], options=a.get("options") or {}),
    ),
    "list_voices": (
        "Read-only, human-only: list voices exposed by one configured provider. This can contact that provider's API.",
        S(provider=STR),
        lambda ws, a: _list_voices(ws, a["provider"]),
    ),
    "list_crew_runs": ("Read-only: the studio crew's runs in a project (agent, task, status, steps, LLM cost). Starting, stopping and undoing a run is human-only.", S(name=STR),
                       lambda ws, a: {"runs": _runs().list_runs(ws, a["name"])}),
    "get_crew_run": ("Read-only: one crew run with its step log, document diffs, proposals and batch.", S(name=STR, id=STR), lambda ws, a: _runs().get_run(ws, a["name"], a["id"])),
    "search_library": ("Search the workspace library of generated media. Human-session only because it can reveal data across projects.", S(q={"type": "string", "optional": True}), lambda ws, a: __import__("aistudio.library", fromlist=["search"]).search(ws.root, a.get("q", ""))),
    "remix": (
        "Create a proposal pre-filled from an output's .meta.json file (nothing is approved or spent). Pre-fills today's proposal for the same kind and target. A human approves the returned proposal before execution.",
        S(name=STR, meta=STR),
        lambda ws, a: ws.remix(a["name"], a.get("meta") or a.get("meta_rel") or a.get("meta_file"), reveal_code=False),
    ),
    "propose_variants": (
        "Freeze N candidates (2-4) of one still or clip as ONE awaiting-approval batch: N separate items, each with its own price, request hash and proposal; the total is N times the unit price. Nothing is approved or spent; a human approves the batch.",
        S(name=STR, kind={"type": "string", "enum": ["image", "clip"]}, target=STR, count={"type": "integer", "description": "Number of variants (2-4)"}),
        lambda ws, a: ws.propose_variants(a["name"], a["kind"], a["target"], int(a["count"]), actor="mcp"),
    ),
    "select_version": (
        "Choose version k of a still or clip. Unselected versions are moved to _discarded with their cost (never deleted); the shot or asset records selected_version, and the timeline/first-frame source points at the chosen version. Free.",
        S(name=STR, kind={"type": "string", "enum": ["image", "clip"]}, target=STR, version={"type": "integer", "description": "Version number to select (e.g. 1, 2)"}),
        lambda ws, a: ws.select_version(a["name"], a["kind"], a["target"], int(a.get("version", a.get("k")))),
    ),
    "drift_check": (
        "Create a proposal for a paid identity-drift check of a shot or still (scores each character against its reference images in checks/<id>.json; verification flags scores below 0.6). Nothing is spent until a human approves the proposal.",
        S(name=STR, target=STR),
        lambda ws, a: ws.drift_check(a["name"], a["target"]),
    ),
}


FREE_READ = ("get_project", "read_doc", "get_brief", "get_model_setup", "get_todos", "get_verification", "get_proposal", "get_spec", "get_costs",
             "list_providers", "production_progress", "get_batch", "get_edit", "unregistered_stills", "list_recipes", "list_formats")
FREE_WRITE = ("write_doc", "update_brief", "rename_asset", "rename_shot", "convert_story", "update_shots", "update_images", "update_edit",
              "import_stills", "add_todo", "toggle_todo", "remove_todo", "export_edit", "export_project")
PAID = ("propose", "analyze_character", "edit_still", "extend_clip", "clip_tool", "audio_tool", "generate_all_plan", "build_identity_sheet",
        "remix", "propose_variants", "drift_check")
# approve/execute/override/cancel/delete/budget tools, tools that reveal codes, and tools that reach outside the run's project
# (other projects, trash, local file paths, the job ledger of every project) are never crew tools.
APPROVAL = ("approve_budget", "approve_proposal", "approve_batch", "approve_shot", "run_proposal", "run_batch", "reject_proposal", "set_max_attempts",
            "estimate", "discard", "restore", "select_version")
HUMAN_ONLY = ("delete_project", "create_project", "list_projects", "list_trash", "restore_trash", "upload_image", "list_jobs", "get_job",
              "list_crew_runs", "get_crew_run", "search_library", "plan_recipe", "list_voices")      # reading runs is for humans and MCP; a crew agent has no use for it

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
