"""MCP server (stdio, newline-delimited JSON-RPC) so AI agents can drive AI Studio projects.  Standard library only.

SAFETY BY DESIGN: paid tools only PROPOSE (nothing is spent). There is NO tool to approve a budget, approve a proposal, approve a
clip, or switch to real mode: those are human actions in the web UI or terminal. `run_proposal` only executes a proposal a human
already approved, and the engine re-checks the gates.

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
TOOLS = {
    "list_projects": ("List projects with spend and budget status.", S(), lambda ws, a: ws.list_projects()),
    "create_project": ("Create a project folder from the guided templates.", S(name=STR), lambda ws, a: {"name": ws.create_project(a["name"])}),
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
    "estimate": ("Compute the budget estimate (free). A HUMAN must approve it in the UI before anything can run.", S(name=STR, failure={"type": "number", "optional": True}), lambda ws, a: ws.estimate(a["name"], float(a.get("failure", 0.2)))),
    "propose": ("Propose a PAID action (nothing is spent). kind = image | clip | review; target = image id or shot id. Returns the price and proposal id; ask the human to approve it in the web UI, then call run_proposal.",
                S(name=STR, kind={"type": "string", "enum": ["image", "clip", "review"]}, target=STR), lambda ws, a: ws.propose(a["name"], a["kind"], a["target"], reveal_code=False)),
    "get_proposal": ("Status of a proposal: pending | approved | used | rejected | expired | void.", S(name=STR, id=STR), lambda ws, a: ws.proposal_status(a["name"], a["id"])),
    "run_proposal": ("Execute a proposal a human has ALREADY approved (spends money in real mode). Fails if not approved, changed, expired or over budget.", S(name=STR, id=STR), lambda ws, a: ws.execute(a["name"], a["id"])),
    "get_costs": ("Cost log, used vs discarded split, budget.", S(name=STR), lambda ws, a: ws.costs(a["name"])),
    "discard": ("Move a clip/still to _discarded (never deletes) with a reason.", S(name=STR, rel=STR, reason={"type": "string", "optional": True}), lambda ws, a: ws.discard(a["name"], a["rel"], a.get("reason", ""))),
    "restore": ("Restore a discarded file.", S(name=STR, rel=STR), lambda ws, a: {"file": ws.restore(a["name"], a["rel"])}),
    "list_providers": ("Connected AI providers (id, label, type, status). There is no app-wide mode: each project is a test project or a real one.", S(), lambda ws, a: {"providers": [{k: v for k, v in p.items() if k in ("id", "label", "type", "enabled", "status")} for p in ws.providers_list()["providers"] if p["type"] != "fake"]}),
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
