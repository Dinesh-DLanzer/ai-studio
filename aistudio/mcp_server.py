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

from aistudio import approvals, jobs, notifications
from aistudio.service import REPO, ServiceError, Workspace
from aistudio.tool_registry import S, STR, TOOLS, _no_job  # noqa: F401  (TOOLS lives in aistudio/tool_registry.py)

PROTOCOL = "2025-11-25"
SUPPORTED_PROTOCOLS = ("2025-11-25", "2025-06-18", "2024-11-05")


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


def _destination(prop):
    """What the human must see before approving: which provider gets which files (a real person's photo may be among them)."""
    sm = prop.get("summary") or {}
    files = [f for f in [sm.get("first_frame"), sm.get("end_frame"), sm.get("file"), *(sm.get("refs") or []), *(sm.get("files") or [])] if f]
    where = f" via provider '{sm['provider']}'" if sm.get("provider") else ""
    sent = f" Files sent to the provider: {', '.join(dict.fromkeys(files))}." if files else " No project files are sent."
    return where, sent


def _approve_proposal_mcp(ws, a, session=None):
    name, pid = a["name"], a["id"]
    prop = ws.proposal_status(name, pid)
    if a.get("confirm") is not None:
        raise ServiceError("confirm=true is not human approval; use MCP elicitation or the one-time fallback code")
    request_digest = prop.get("hash")
    where, sent = _destination(prop)
    message = f"Approve {prop['kind']} '{prop['shot']}' with {prop.get('model', '')}{where} for ${prop['price']:.3f}?{sent}"
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


def _approve_batch_mcp(ws, a, session=None):
    name, bid = a["name"], a["id"]
    batch = ws.batches.get(name, bid)
    if a.get("confirm") is not None:
        raise ServiceError("confirm=true is not human approval; use MCP elicitation or the one-time fallback code")
    message = f"Approve batch of {len(batch['items'])} items totalling ${batch['total']:.3f}? Each item runs at its listed price only."
    if a.get("code"):
        if not a.get("code_id"):
            raise ServiceError("code_id is required with an approval code")
        try:
            approvals.redeem_code(ws.pdir(name), a["code_id"], a["code"], bid, "batch", batch["batch_hash"], _approval_secret(ws))
            notifications.mark_used(a["code_id"])
        except approvals.ApprovalError as e:
            raise ServiceError(str(e)) from None
    elif not _elicit_approval(session, message, batch["total"]):
        return _fallback_approval(ws, name, bid, "batch", batch["batch_hash"], message)
    ws.batches.approve(name, bid, batch["batch_hash"])
    return {"ok": True, "approved": True, "batch_id": bid, "message": f"Batch {bid} approved (${batch['total']:.3f}). Run it with run_batch(name='{name}', id='{bid}')."}


def _run_batch_mcp(ws, a):
    if a.get("override") or a.get("confirm") is not None:
        raise ServiceError("override and confirm are not accepted; a batch runs only after a human approved it")
    return ws.batches.run(a["name"], a["id"])


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
            elif name == "approve_batch":
                result = _approve_batch_mcp(ws, args, session=session)
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
