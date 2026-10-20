"""MCP server (stdio, newline-delimited JSON-RPC) so AI agents can drive AI Studio projects.  Standard library only.

APPROVAL BY DESIGN: AI agents (Claude Code, OpenCode, Codex, Antigravity CLI/IDE) can perform ALL processes
end-to-end, including story conversion, budget approvals, proposals, shot approvals, and project trashing/deletion.
High-impact and spending actions enforce explicit confirmation parameters (e.g. confirm=true or confirm=project_name),
prompting the client agent to show interactive user approval popups before execution.

Run:  python3 -m aistudio.mcp_server      (AISTUDIO_HOME = workspace folder; default: the repo)
Claude Code:  claude mcp add ai-studio -- python3 -m aistudio.mcp_server
"""
import json
import os
import sys

from aistudio.service import REPO, ServiceError, Workspace

PROTOCOL = "2024-11-05"
S = lambda **props: {"type": "object", "properties": props, "required": [k for k, v in props.items() if not v.get("optional")]}
STR = {"type": "string"}


def _approve_budget_mcp(ws, a):
    b = ws.overview(a["name"]).get("budget") or {}
    if not b.get("estimate"):
        b = ws.estimate(a["name"])
    est, stop = b.get("estimate", 0), b.get("stop_loss", 0)
    if not a.get("confirm"):
        raise ServiceError(
            f"Budget approval requires confirm=true. Ask user in CLI: 'Approve project budget estimate of ${est:.2f} (stop-loss: ${stop:.2f})?' "
            f"and on confirmation call approve_budget(name='{a['name']}', confirm=true)."
        )
    ws.approve_budget(a["name"])
    return {
        "ok": True,
        "approved": True,
        "project": a["name"],
        "budget": ws.overview(a["name"]).get("budget"),
        "message": f"Budget approved (${est:.2f}). Generation proposals can now be created and executed.",
    }


def _approve_proposal_mcp(ws, a):
    prop = ws.proposal_status(a["name"], a["id"])
    if not a.get("confirm"):
        raise ServiceError(
            f"Proposal approval requires confirm=true. Ask user in CLI: 'Approve {prop['kind']} {prop['shot']} for ${prop['price']:.3f}?' "
            f"and on confirmation call approve_proposal(name='{a['name']}', id='{a['id']}', confirm=true)."
        )
    ws.approve_human(a["name"], a["id"])
    return {
        "ok": True,
        "approved": True,
        "proposal_id": a["id"],
        "message": f"Proposal {a['id']} approved (${prop['price']:.3f}). Run it via run_proposal(name='{a['name']}', id='{a['id']}').",
    }


def _estimate_mcp(ws, a):
    b = ws.estimate(a["name"], float(a.get("failure", 0.2)))
    est, stop = b.get("estimate", 0), b.get("stop_loss", 0)
    b["cli_approval_prompt"] = f"Approve estimated project budget of ${est:.2f} (stop-loss: ${stop:.2f})?"
    b["next_step"] = f"Ask user: '{b['cli_approval_prompt']}'. On confirmation call approve_budget(name='{a['name']}', confirm=true). Do NOT redirect user to web UI."
    return b


def _propose_mcp(ws, a):
    res = ws.propose(a["name"], a["kind"], a["target"], reveal_code=False)
    res["cli_approval_prompt"] = f"Approve {res['kind']} '{res['shot']}' with {res['model']} for ${res['price']:.3f}?"
    res["next_step"] = f"Ask user: '{res['cli_approval_prompt']}'. On confirmation call run_proposal(name='{a['name']}', id='{res['id']}', confirm=true). Do NOT redirect user to web UI."
    return res


def _run_proposal_mcp(ws, a):
    name, pid = a["name"], a["id"]
    prop = ws.proposal_status(name, pid)
    overview = ws.overview(name)
    b = overview.get("budget") or {}
    if not b.get("approved"):
        est = b.get("estimate", 0)
        raise ServiceError(
            f"Project budget is not approved yet (estimate: ${est:.2f}). "
            f"Ask the user in terminal: 'Approve budget estimate of ${est:.2f}?' "
            f"and on confirmation call approve_budget(name='{name}', confirm=true). "
            f"Do NOT tell the user to open the web UI."
        )
    if prop["status"] == "pending":
        if a.get("confirm"):
            ws.approve_human(name, pid)
        else:
            kind, target, model, price = prop.get("kind"), prop.get("shot"), prop.get("model"), prop.get("price", 0)
            raise ServiceError(
                f"Proposal {pid} ({kind} '{target}' via {model}) is pending approval for ${price:.3f}. "
                f"Ask the user in terminal: 'Approve {kind} {target} for ${price:.3f}?' "
                f"and on confirmation call run_proposal(name='{name}', id='{pid}', confirm=true) "
                f"or approve_proposal(name='{name}', id='{pid}', confirm=true). "
                f"Do NOT tell the user to open the web UI."
            )
    override = bool(a.get("override", False))
    return ws.execute(name, pid, override=override)


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
    "estimate": ("Compute budget estimate (free). Approve via approve_budget in CLI or web UI before generating.", S(name=STR, failure={"type": "number", "optional": True}), lambda ws, a: _estimate_mcp(ws, a)),
    "approve_budget": (
        "Approve the estimated budget cap for a project so video/image generation can proceed. High-impact: requires confirm=true to trigger user approval in CLI.",
        S(name=STR, confirm={"type": "boolean", "description": "Explicit approval confirmation"}),
        lambda ws, a: _approve_budget_mcp(ws, a),
    ),
    "propose": ("Propose a PAID action (nothing is spent). kind = image | clip | review; target = image id or shot id. Returns price and proposal id; approve and run via run_proposal(..., confirm=true) or approve_proposal.",
                S(name=STR, kind={"type": "string", "enum": ["image", "clip", "review"]}, target=STR), lambda ws, a: _propose_mcp(ws, a)),
    "get_proposal": ("Status of a proposal: pending | approved | used | rejected | expired | void.", S(name=STR, id=STR), lambda ws, a: ws.proposal_status(a["name"], a["id"])),
    "approve_proposal": (
        "Approve a pending generation proposal (image, clip, or review). High-impact: requires confirm=true to trigger user approval popup in CLI.",
        S(name=STR, id=STR, confirm={"type": "boolean", "description": "Explicit approval confirmation"}),
        lambda ws, a: _approve_proposal_mcp(ws, a),
    ),
    "reject_proposal": (
        "Reject and cancel a pending proposal.",
        S(name=STR, id=STR),
        lambda ws, a: ws.reject(a["name"], a["id"]) or {"ok": True, "rejected": a["id"]},
    ),
    "run_proposal": (
        "Execute a generation proposal (spends money in real mode). If proposal is pending approval, set confirm=true to approve and execute in one step with user confirmation. Set override=true to override attempt limits (e.g. past 3 attempts) or stop-loss limits.",
        S(name=STR, id=STR, confirm={"type": "boolean", "optional": True, "description": "Confirm approval and execute (triggers user approval popup in CLI)"},
          override={"type": "boolean", "optional": True, "description": "Override attempt limits (e.g. past 3 attempts) or stop-loss limits"}),
        lambda ws, a: _run_proposal_mcp(ws, a),
    ),
    "set_max_attempts": (
        "Set maximum generation attempts allowed per shot for a project (e.g. 5, 10, 20).",
        S(name=STR, max_attempts={"type": "integer", "description": "Maximum attempts allowed per shot"}),
        lambda ws, a: ws.set_max_attempts(a["name"], a["max_attempts"]),
    ),
    "approve_shot": (
        "Approve a generated video clip for a shot.",
        S(name=STR, shot_id=STR),
        lambda ws, a: ws.approve_shot(a["name"], a["shot_id"]) or {"ok": True, "approved_shot": a["shot_id"]},
    ),
    "get_costs": ("Cost log, used vs discarded split, budget.", S(name=STR), lambda ws, a: ws.costs(a["name"])),
    "discard": ("Move a clip/still to _discarded (never deletes) with a reason.", S(name=STR, rel=STR, reason={"type": "string", "optional": True}), lambda ws, a: ws.discard(a["name"], a["rel"], a.get("reason", ""))),
    "restore": ("Restore a discarded file.", S(name=STR, rel=STR), lambda ws, a: {"file": ws.restore(a["name"], a["rel"])}),
    "list_providers": ("Connected AI providers (id, label, type, status). There is no app-wide mode: each project is a test project or a real one.", S(), lambda ws, a: {"providers": [{k: v for k, v in p.items() if k in ("id", "label", "type", "enabled", "status")} for p in ws.providers_list()["providers"] if p["type"] != "fake"]}),
    "production_progress": ("Get production checklist groups, queue items, and next action.", S(name=STR), lambda ws, a: ws.production_progress(a["name"])),
    "generate_all_plan": ("Plan batch generation for all pending items (free proposal generation).", S(name=STR), lambda ws, a: ws.generate_all_plan(a["name"])),
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


def tool_list():
    return [{"name": n, "description": d, "inputSchema": schema} for n, (d, schema, _) in TOOLS.items()]


def handle(msg, ws):
    """Return a response dict, or None for notifications."""
    method, mid = msg.get("method"), msg.get("id")
    if mid is None:
        return None
    ok = lambda result: {"jsonrpc": "2.0", "id": mid, "result": result}
    err = lambda code, m: {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": m}}
    if method == "initialize":
        return ok({"protocolVersion": PROTOCOL, "capabilities": {"tools": {}}, "serverInfo": {"name": "ai-studio", "version": "0.1.0"}})
    if method == "ping":
        return ok({})
    if method == "tools/list":
        return ok({"tools": tool_list()})
    if method == "tools/call":
        p = msg.get("params") or {}
        name, args = p.get("name"), p.get("arguments") or {}
        if name not in TOOLS:
            return err(-32602, f"unknown tool {name}")
        try:
            missing = [k for k in TOOLS[name][1]["required"] if k not in args]
            if missing:
                raise ServiceError(f"missing arguments: {', '.join(missing)}")
            result, is_err = TOOLS[name][2](ws, args), False
        except ServiceError as e:
            result, is_err = {"error": str(e)}, True
        except Exception as e:  # provider/network problems: report, never crash the server
            result, is_err = {"error": f"{type(e).__name__}: {e}"}, True
        return ok({"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False, indent=2)}], "isError": is_err})
    return err(-32601, f"method not found: {method}")


def main():
    home = os.environ.get("AISTUDIO_HOME") or REPO
    ws = Workspace(home)
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            resp = handle(json.loads(line), ws)
        except json.JSONDecodeError:
            resp = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}}
        if resp is not None:
            sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
