"""MCP server (stdio, newline-delimited JSON-RPC) so agents can drive AI Studio projects. Standard library only.

APPROVAL BY DESIGN: agents can inspect projects and create proposals, but a human must approve every budget and
paid proposal. MCP clients advertising form elicitation receive an ``elicitation/create`` dialog. Other clients get
a one-time code challenge; the code is shown only in the local web notification and ``aistudio serve`` stderr.
``confirm=true`` is never an approval signal. ``delete_project`` remains a non-spending name confirmation.

Run:  python3 -m aistudio.mcp_server      (AISTUDIO_HOME = workspace folder; default: the repo)
Claude Code:  claude mcp add ai-studio -- python3 -m aistudio.mcp_server
"""
import json
import os
import sys

from aistudio import approvals, notifications
from aistudio.service import REPO, ServiceError, Workspace

PROTOCOL = "2025-11-25"
SUPPORTED_PROTOCOLS = ("2025-11-25", "2025-06-18", "2024-11-05")
S = lambda **props: {"type": "object", "properties": props, "required": [k for k, v in props.items() if not v.get("optional")]}
STR = {"type": "string"}


class MCPConnection:
    """Small transport seam for nested server-to-client MCP requests and tests."""

    def __init__(self, request=None, client_capabilities=None, protocol_version=None):
        self.request_callback = request
        self.client_capabilities = client_capabilities or {}
        self.protocol_version = protocol_version or PROTOCOL

    def supports(self, mode="form"):
        if self.protocol_version not in ("2025-06-18", "2025-11-25"):
            return False
        caps = self.client_capabilities or {}
        if not isinstance(caps, dict) or "elicitation" not in caps:
            return False
        elicitation = caps.get("elicitation")
        if elicitation == {}:
            return mode == "form"
        return mode in elicitation

    def request(self, method, params):
        if not self.request_callback:
            return None
        return self.request_callback(method, params)


def _client_capabilities(params):
    params = params or {}
    meta = params.get("_meta") or {}
    namespaced = meta.get("io.modelcontextprotocol/clientCapabilities")
    return namespaced if isinstance(namespaced, dict) else (params.get("capabilities") or {})


def _budget_request(ws, name):
    b = ws.overview(name).get("budget") or {}
    if not b.get("estimate"):
        b = ws.estimate(name)
    return b, approvals.request_hash("budget", name, "budget", b.get("estimate", 0), {"estimate": b.get("estimate", 0), "stop_loss": b.get("stop_loss", 0)})


def _approval_secret(ws):
    """Load or create the MCP fallback HMAC key in the external secret store."""
    ref = "mcp-approval-hmac"
    fields = ws.secrets.get(ref)
    if not fields.get("secret"):
        import secrets as _secrets
        ws.secrets.set(ref, {"secret": _secrets.token_urlsafe(32)})
        fields = ws.secrets.get(ref)
    return fields["secret"]


def _fallback_approval(ws, name, reference, kind, request_hash_value, message):
    challenge = approvals.issue_code(ws.pdir(name), reference, kind, request_hash_value, _approval_secret(ws))
    notifications.publish_approval(ws.pdir(name), challenge["id"], challenge["code"], message)
    # Only an interactive human terminal gets the code on stderr. A piped MCP
    # client's stderr must not become another agent-visible approval channel.
    if getattr(sys.stderr, "isatty", lambda: False)():
        print(f"[AI Studio approval] {message} Code ID: {challenge['id']}. One-time code: {challenge['code']} (expires in 10 minutes)", file=sys.stderr, flush=True)
    return {"approval_needed": True, "code_id": challenge["id"], "expires": challenge["expires"],
            "message": message, "next_step": f"Have the human provide the one-time code for code_id '{challenge['id']}' and call again with code and code_id. The code is not in this response."}


def _elicit_approval(session, message, price):
    if not session or not session.supports("form"):
        return False
    response = session.request("elicitation/create", {
        "mode": "form",
        "message": message,
        "requestedSchema": {"type": "object", "properties": {
            "approve": {"type": "boolean", "title": f"I approve ${float(price):.3f}", "description": "Tick only after reviewing the exact request and price.", "default": False}
        }, "required": ["approve"]},
    }) or {}
    if response.get("action") != "accept":
        raise ServiceError(f"human approval {response.get('action', 'was not accepted')}")
    if not isinstance(response.get("content"), dict) or response["content"].get("approve") is not True:
        raise ServiceError("human approval checkbox was not ticked")
    return True


def _approve_budget_mcp(ws, a, session=None):
    name = a["name"]
    b, request_digest = _budget_request(ws, name)
    est, stop = b.get("estimate", 0), b.get("stop_loss", 0)
    if a.get("confirm") is not None:
        raise ServiceError("confirm=true is not human approval; use MCP elicitation or the one-time fallback code")
    if a.get("code"):
        if not a.get("code_id"):
            raise ServiceError("code_id is required with an approval code")
        try:
            approvals.redeem_code(ws.pdir(name), a["code_id"], a["code"], name, "budget", request_digest, _approval_secret(ws))
            notifications.mark_used(a["code_id"])
        except approvals.ApprovalError as e:
            raise ServiceError(str(e)) from None
    elif not _elicit_approval(session, f"Approve project budget estimate of ${est:.2f} (stop-loss: ${stop:.2f})?", est):
        return _fallback_approval(ws, name, name, "budget", request_digest, f"Approve project budget estimate of ${est:.2f} (stop-loss: ${stop:.2f})?")
    current, current_digest = _budget_request(ws, name)
    if current_digest != request_digest:
        raise ServiceError("budget changed while awaiting human approval; estimate again and ask the human to approve it")
    ws.approve_budget(name)
    return {"ok": True, "approved": True, "project": name, "budget": ws.overview(name).get("budget"),
            "message": f"Budget approved (${est:.2f}). Generation proposals can now be created and executed."}


def _approve_proposal_mcp(ws, a, session=None):
    name, pid = a["name"], a["id"]
    prop = ws.proposal_status(name, pid)
    if a.get("confirm") is not None:
        raise ServiceError("confirm=true is not human approval; use MCP elicitation or the one-time fallback code")
    request_digest = prop.get("hash")
    message = f"Approve {prop['kind']} '{prop['shot']}' with {prop.get('model', '')} for ${prop['price']:.3f}?"
    if a.get("code"):
        if not a.get("code_id"):
            raise ServiceError("code_id is required with an approval code")
        try:
            approvals.redeem_code(ws.pdir(name), a["code_id"], a["code"], pid, "proposal", request_digest, _approval_secret(ws))
            notifications.mark_used(a["code_id"])
        except approvals.ApprovalError as e:
            raise ServiceError(str(e)) from None
    elif not _elicit_approval(session, message, prop["price"]):
        return _fallback_approval(ws, name, pid, "proposal", request_digest, message)
    ws.approve_human(name, pid)
    return {"ok": True, "approved": True, "proposal_id": pid,
            "message": f"Proposal {pid} approved (${prop['price']:.3f}). Run it via run_proposal(name='{name}', id='{pid}')."}


def _estimate_mcp(ws, a):
    b = ws.estimate(a["name"], float(a.get("failure", 0.2)))
    est, stop = b.get("estimate", 0), b.get("stop_loss", 0)
    b["human_approval"] = f"Approve estimated project budget of ${est:.2f} (stop-loss: ${stop:.2f}) using approve_budget; MCP will show an elicitation dialog when supported."
    return b


def _propose_mcp(ws, a):
    res = ws.propose(a["name"], a["kind"], a["target"])
    res["human_approval"] = f"Use approve_proposal or run_proposal; the MCP client will show the exact price and request for human approval."
    return res


def _human_only_shot_approval(ws, a):
    raise ServiceError("clip approval is human-only; use the web page or a human session")


def _human_only_attempt_limit(ws, a):
    raise ServiceError("attempt limits are human-only; use the web page or a human session")


def _run_proposal_mcp(ws, a, session=None):
    if a.get("override"):
        raise ServiceError("override is human-web-only; MCP agents cannot bypass stop-loss or attempt gates")
    name, pid = a["name"], a["id"]
    prop = ws.proposal_status(name, pid)
    overview = ws.overview(name)
    b = overview.get("budget") or {}
    if not b.get("approved"):
        est = b.get("estimate", 0)
        raise ServiceError(f"Project budget is not approved yet (estimate: ${est:.2f}). Use approve_budget; confirm=true is not accepted.")
    if a.get("confirm") is not None:
        raise ServiceError("confirm=true is not human approval; use MCP elicitation or the one-time fallback code")
    if prop["status"] == "pending":
        approval_args = {"name": name, "id": pid}
        if a.get("code"):
            approval_args.update({"code": a.get("code"), "code_id": a.get("code_id")})
        approval = _approve_proposal_mcp(ws, approval_args, session=session)
        if approval.get("approval_needed"):
            return approval
    return ws.execute(name, pid)


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
    "estimate": ("Compute budget estimate (free). A human must approve it through MCP elicitation or the one-time fallback code before generating.", S(name=STR, failure={"type": "number", "optional": True}), lambda ws, a: _estimate_mcp(ws, a)),
    "approve_budget": (
        "Request human approval for the exact estimated budget. MCP elicitation is used when the client advertises it; otherwise a one-time code challenge is returned. confirm=true is not accepted.",
        S(name=STR, code={"type": "string", "optional": True}, code_id={"type": "string", "optional": True}),
        lambda ws, a: _approve_budget_mcp(ws, a),
    ),
    "propose": ("Propose a PAID action (nothing is spent). kind = image | clip | review; target = image id or shot id. A human must approve the exact proposal before it can run.",
                S(name=STR, kind={"type": "string", "enum": ["image", "clip", "review"]}, target=STR), lambda ws, a: _propose_mcp(ws, a)),
    "get_proposal": ("Status of a proposal: pending | approved | used | rejected | expired | void.", S(name=STR, id=STR), lambda ws, a: ws.proposal_status(a["name"], a["id"])),
    "approve_proposal": (
        "Request human approval for a pending proposal. Uses MCP elicitation when available; otherwise returns a one-time code challenge. confirm=true is not accepted.",
        S(name=STR, id=STR, code={"type": "string", "optional": True}, code_id={"type": "string", "optional": True}),
        lambda ws, a: _approve_proposal_mcp(ws, a),
    ),
    "reject_proposal": (
        "Reject and cancel a pending proposal.",
        S(name=STR, id=STR),
        lambda ws, a: ws.reject(a["name"], a["id"]) or {"ok": True, "rejected": a["id"]},
    ),
    "run_proposal": (
        "Execute a proposal only after human approval. Pending proposals use MCP elicitation or a one-time code challenge; confirm=true and override=true are not accepted from agents.",
        S(name=STR, id=STR, code={"type": "string", "optional": True}, code_id={"type": "string", "optional": True}),
        lambda ws, a: _run_proposal_mcp(ws, a),
    ),
    "set_max_attempts": (
        "Human-only attempt limit setting. Agents cannot change generation attempt limits; use the web page or a human session.",
        S(name=STR, max_attempts={"type": "integer", "description": "Maximum attempts allowed per shot"}),
        _human_only_attempt_limit,
    ),
    "approve_shot": (
        "Human-only clip decision. Agents may inspect clips but cannot approve them through MCP; use the web page or a human session.",
        S(name=STR, shot_id=STR),
        _human_only_shot_approval,
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


def handle(msg, ws, session=None):
    """Return a response dict, or None for notifications."""
    method, mid = msg.get("method"), msg.get("id")
    if mid is None:
        return None
    ok = lambda result: {"jsonrpc": "2.0", "id": mid, "result": result}
    err = lambda code, m: {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": m}}
    if method == "initialize":
        params = msg.get("params") or {}
        requested = params.get("protocolVersion")
        selected = requested if requested in SUPPORTED_PROTOCOLS else PROTOCOL
        caps = _client_capabilities(params)
        probe = session or MCPConnection(client_capabilities=caps, protocol_version=selected)
        probe.client_capabilities = caps
        probe.protocol_version = selected
        server_caps = {"tools": {}}
        if probe.supports("form"):
            server_caps["elicitation"] = {"form": {}}
        return ok({"protocolVersion": selected, "capabilities": server_caps, "serverInfo": {"name": "ai-studio", "version": "0.1.0"}})
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
            if name == "approve_budget":
                result = _approve_budget_mcp(ws, args, session=session)
            elif name == "approve_proposal":
                result = _approve_proposal_mcp(ws, args, session=session)
            elif name == "run_proposal":
                result = _run_proposal_mcp(ws, args, session=session)
            else:
                result = TOOLS[name][2](ws, args)
            is_err = False
        except ServiceError as e:
            result, is_err = {"error": str(e)}, True
        except Exception as e:  # provider/network problems: report, never crash the server
            result, is_err = {"error": f"{type(e).__name__}: {e}"}, True
        return ok({"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False, indent=2)}], "isError": is_err})
    return err(-32601, f"method not found: {method}")


class StdioConnection(MCPConnection):
    """Synchronous newline JSON-RPC transport supporting nested elicitation requests."""

    def __init__(self, reader, writer):
        super().__init__()
        self.reader, self.writer, self.next_id = reader, writer, 1

    def _write(self, message):
        self.writer.write(json.dumps(message, ensure_ascii=False) + "\n")
        self.writer.flush()

    def request(self, method, params):
        request_id = f"server-elicitation-{self.next_id}"
        self.next_id += 1
        self._write({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
        while True:
            line = self.reader.readline()
            if not line:
                raise ServiceError("MCP client disconnected during human approval")
            try:
                incoming = json.loads(line)
            except json.JSONDecodeError:
                continue
            if incoming.get("id") == request_id and "method" not in incoming:
                if "error" in incoming:
                    raise ServiceError("MCP client returned an elicitation error")
                return incoming.get("result") or {}
            # Preserve the one-request-at-a-time stdio contract while still
            # servicing notifications or a nested request from the client.
            nested = handle(incoming, self._workspace, self)
            if nested is not None:
                self._write(nested)


def serve(reader, writer, ws):
    session = StdioConnection(reader, writer)
    session._workspace = ws
    while True:
        line = reader.readline()
        if not line:
            break
        line = line.strip()
        if not line:
            continue
        try:
            resp = handle(json.loads(line), ws, session)
        except json.JSONDecodeError:
            resp = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}}
        except Exception as e:
            resp = {"jsonrpc": "2.0", "id": None, "error": {"code": -32603, "message": str(e)}}
        if resp is not None:
            session._write(resp)


def main():
    home = os.environ.get("AISTUDIO_HOME") or REPO
    serve(sys.stdin, sys.stdout, Workspace(home))


if __name__ == "__main__":
    main()
