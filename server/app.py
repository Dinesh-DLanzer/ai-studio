"""Local web API for AI Studio. Binds to 127.0.0.1 only. Every call needs the session token printed at start-up,
and state-changing calls are checked for a local Origin (blocks drive-by requests from other websites).

The HUMAN channel: only this server (used by the web UI) may reveal an approval code. The MCP server never does.
"""
import asyncio
import contextlib
import json
import os
import secrets
import threading
import uuid
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from starlette.background import BackgroundTask
from fastapi.staticfiles import StaticFiles

from aistudio import apikeys, editor as editormod, importzip as importmod, notifications
from aistudio.service import REPO, ServiceError, Workspace
from server import api_docs

ALLOWED_SUFFIX = {".png", ".jpg", ".jpeg", ".webp", ".svg", ".mp4", ".json", ".md", ".csv", ".txt", ".mp3", ".wav", ".m4a", ".aac", ".ogg"}
SERVE_DIRS = {"stills", "clips", "checks", "audio", "exports", "elements"}


def _stop_chatgpt_listener(app_state):
    timer = getattr(app_state, "chatgpt_timer", None)
    if timer:
        try:
            timer.cancel()
        except Exception:
            pass
        app_state.chatgpt_timer = None
    listener = getattr(app_state, "chatgpt_listener", None)
    if listener:
        app_state.chatgpt_listener = None
        try:
            listener.shutdown()
        except Exception:
            pass
        try:
            listener.server_close()
        except Exception:
            pass


def create_app(root=None, token=None, rates_path=None, transport=None, static_dir=None, auto_verify=True, secret_store=None):
    ws = Workspace(root or os.environ.get("AISTUDIO_HOME") or REPO, rates_path=rates_path, transport=transport, auto_verify=auto_verify, secrets=secret_store)
    token = token or os.environ.get("AISTUDIO_TOKEN") or secrets.token_urlsafe(16)

    @contextlib.asynccontextmanager
    async def lifespan(app_instance: FastAPI):
        yield
        _stop_chatgpt_listener(app_instance.state)

    app = FastAPI(title="AI Studio", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.state.ws, app.state.token, jobs, lock = ws, token, {}, threading.Lock()

    @app.middleware("http")
    async def local_only(request: Request, call_next):
        host = (request.headers.get("host") or "").split(":")[0]
        if host not in ("127.0.0.1", "localhost", "testserver"):
            return JSONResponse({"error": "host not allowed"}, status_code=403)
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            origin = request.headers.get("origin")
            if origin and (origin.split("://", 1)[-1].split(":")[0] not in ("127.0.0.1", "localhost", "testserver")):
                return JSONResponse({"error": "origin not allowed"}, status_code=403)
        return await call_next(request)

    def given_token(request: Request):
        bearer = request.headers.get("authorization") or ""
        return request.headers.get("x-aistudio-token") or (bearer[7:].strip() if bearer.lower().startswith("bearer ") else "") or request.query_params.get("token") or ""

    def auth(request: Request):
        """The page's session token = a human (everything).  An API key (aisk_...) = an agent: only the routes marked agent in api_docs,
        i.e. what the MCP tools can do.  Anything else is refused."""
        given = given_token(request)
        if secrets.compare_digest(given, token):
            request.state.scope = "session"
            return
        rec = apikeys.verify(ws.root, given) if given.startswith(apikeys.PREFIX) else None
        if not rec:
            raise HTTPException(401, "missing or wrong session token or API key")
        route = request.scope.get("route")
        if not api_docs.agent_allowed(request.method, getattr(route, "path", "")):
            raise HTTPException(403, "this API key can read, write documents, estimate, propose and run what a human already approved; approving, budgets, providers, keys and deleting need the page")
        request.state.scope = "agent"

    def guard(fn, *a, **kw):
        try:
            return fn(*a, **kw)
        except ServiceError as e:
            if hasattr(e, "diff"):
                return JSONResponse({"detail": str(e), "budget_diff": e.diff}, status_code=400)
            raise HTTPException(400, str(e)) from None

    @app.get("/api/health")
    def health():
        return {"ok": True}

    api = Depends(auth)

    @app.get("/api/projects", dependencies=[api])
    def projects():
        return {"projects": ws.list_projects()}

    @app.post("/api/projects", dependencies=[api])
    async def create(request: Request):
        b = await request.json()
        return {"name": guard(ws.create_project, b.get("name"), bool(b.get("test_pipeline")))}

    @app.post("/api/projects/import", dependencies=[api])
    async def import_project(request: Request, filename: str = "", name: str = ""):
        """Body = the raw zip.  It is streamed to a temp file (never held in memory), validated, and only then installed."""
        import tempfile
        limit = 2 * 1024**3
        tmp = tempfile.NamedTemporaryFile(prefix="aistudio-upload-", suffix=".zip", delete=False)
        try:
            size = 0
            async for chunk in request.stream():
                size += len(chunk)
                if size > limit:
                    return JSONResponse({"detail": "The zip is bigger than 2 GB.", "problems": ["The zip is bigger than 2 GB."]}, status_code=413)
                tmp.write(chunk)
            tmp.close()
            try:
                return await run_in_threadpool(ws.import_project, tmp.name, name, filename)
            except importmod.ImportError_ as e:
                return JSONResponse({"detail": "The zip was not imported: " + e.problems[0] + (f" (and {len(e.problems) - 1} more)" if len(e.problems) > 1 else ""), "problems": e.problems}, status_code=400)
            except ServiceError as e:
                return JSONResponse({"detail": str(e), "problems": [str(e)]}, status_code=400)
        finally:
            tmp.close()
            Path(tmp.name).unlink(missing_ok=True)

    @app.post("/api/projects/{name}/favorite", dependencies=[api])
    async def favorite(name: str, request: Request):
        return guard(ws.set_favorite, name, bool((await request.json()).get("on")))

    @app.get("/api/projects/{name}/generate-all", dependencies=[api])
    def generate_all_plan(name: str):
        return guard(ws.generate_all_plan, name)

    @app.post("/api/projects/{name}/batches", dependencies=[api])
    def create_batch(name: str, request: Request):
        return guard(ws.batches.create, name, "api-key" if getattr(request.state, "scope", "session") == "agent" else "local")

    @app.get("/api/projects/{name}/batches", dependencies=[api])
    def list_batches(name: str):
        return {"batches": guard(ws.batches.list, name)}

    @app.get("/api/projects/{name}/batches/{bid}", dependencies=[api])
    def get_batch(name: str, bid: str):
        return guard(ws.batches.get, name, bid)

    @app.post("/api/projects/{name}/batches/{bid}/approve", dependencies=[api])
    async def approve_batch(name: str, bid: str, request: Request):
        return guard(ws.batches.approve, name, bid, str((await request.json()).get("batch_hash", "")))

    @app.post("/api/projects/{name}/batches/{bid}/run", dependencies=[api])
    def run_batch(name: str, bid: str):
        guard(ws.batches.get, name, bid)
        jid = uuid.uuid4().hex[:10]
        with lock:
            jobs[jid] = {"status": "running"}

        def work():
            try:
                res = ws.batches.run(name, bid)
                with lock:
                    jobs[jid] = {"status": "done", "result": res}
            except Exception as e:   # the batch file already records the failure
                with lock:
                    jobs[jid] = {"status": "error", "error": f"{type(e).__name__}: {e}"}
        threading.Thread(target=work, daemon=True).start()
        return {"job": jid}

    @app.get("/api/projects/{name}", dependencies=[api])
    def overview(name: str):
        ov = guard(ws.overview, name)
        if isinstance(ov, dict):
            ov["activity"] = guard(ws.activity, name)
        return ov

    @app.get("/api/projects/{name}/activity", dependencies=[api])
    def get_activity(name: str):
        return {"activity": guard(ws.activity, name)}

    @app.get("/api/approval-notifications", dependencies=[api])
    def get_approval_notifications(request: Request):
        if getattr(request.state, "scope", "") != "session":
            raise HTTPException(403, "approval notifications require the human session")
        out = []
        for row in ws.list_projects():
            name = row.get("name")
            if not name:
                continue
            for item in notifications.read_approvals(ws.pdir(name)):
                out.append({**item, "project": name})
        return {"notifications": out}

    @app.get("/api/projects/{name}/events", dependencies=[api])
    async def project_events(name: str, request: Request):
        async def event_generator():
            last_activity = ""
            last_files_mtime = 0
            while True:
                if await request.is_disconnected():
                    break
                try:
                    act = guard(ws.activity, name)
                    act_json = json.dumps(act, sort_keys=True)
                    if act_json != last_activity:
                        last_activity = act_json
                        yield f"data: {json.dumps({'type': 'activity', 'activity': act})}\n\n"

                    p = ws.pdir(name)
                    stills_dir = p / "stills"
                    clips_dir = p / "clips"
                    curr_mtime = max(
                        stills_dir.stat().st_mtime if stills_dir.exists() else 0,
                        clips_dir.stat().st_mtime if clips_dir.exists() else 0,
                        (p / "images.json").stat().st_mtime if (p / "images.json").exists() else 0,
                        (p / "shots.json").stat().st_mtime if (p / "shots.json").exists() else 0,
                        (p / "cost_log.csv").stat().st_mtime if (p / "cost_log.csv").exists() else 0,
                    )
                    if curr_mtime > last_files_mtime:
                        if last_files_mtime > 0:
                            yield f"data: {json.dumps({'type': 'refresh'})}\n\n"
                        last_files_mtime = curr_mtime
                except Exception:
                    pass
                await asyncio.sleep(1.0)

        return StreamingResponse(event_generator(), media_type="text/event-stream")

    @app.get("/api/projects/{name}/docs/{fn}", dependencies=[api])
    def get_doc(name: str, fn: str):
        return {"text": guard(ws.get_text, name, fn)}

    @app.put("/api/projects/{name}/docs/{fn}", dependencies=[api])
    async def put_doc(name: str, fn: str, request: Request):
        guard(ws.put_text, name, fn, (await request.json()).get("text", ""))
        return {"ok": True}

    @app.post("/api/projects/{name}/story/convert", dependencies=[api])
    async def convert(name: str, request: Request):
        b = await request.json() if (await request.body()) else {}
        return guard(ws.convert_story, name, True, b.get("model", "google/veo-3.1-lite"), int(b.get("seconds", 4)), b.get("resolution", "720p"))

    @app.put("/api/projects/{name}/shots", dependencies=[api])
    async def put_shots(name: str, request: Request):
        guard(ws.put_shots, name, await request.json())
        return {"ok": True}

    @app.put("/api/projects/{name}/images", dependencies=[api])
    async def put_images(name: str, request: Request):
        guard(ws.put_images, name, await request.json())
        return {"ok": True}

    @app.post("/api/projects/{name}/upload", dependencies=[api])
    async def upload(name: str, rel: str, request: Request, replace: int = 0):
        data = await request.body()
        if len(data) > 25_000_000:
            raise HTTPException(413, "file too large")
        guard(ws.add_file, name, rel, data, bool(replace))
        return {"ok": True}

    @app.post("/api/projects/{name}/character/analyze", dependencies=[api])
    async def analyze_character(name: str, request: Request):
        b = await request.json() if (await request.body()) else {}
        rel = b.get("rel") or b.get("file") or b.get("id") or ""
        return guard(ws.analyze_character_image, name, rel)

    @app.post("/api/projects/{name}/estimate", dependencies=[api])
    async def estimate(name: str, request: Request):
        b = await request.json() if (await request.body()) else {}
        return guard(ws.estimate, name, float(b.get("failure", 0.2)))

    @app.post("/api/projects/{name}/budget/approve", dependencies=[api])
    def approve_budget(name: str):
        return guard(ws.approve_budget, name)

    @app.post("/api/projects/{name}/proposals", dependencies=[api])
    async def propose(name: str, request: Request):
        b = await request.json()
        # the approval code is shown only to the human channel (the page); an API key gets the proposal without it
        return guard(ws.propose, name, b.get("kind"), b.get("target"), getattr(request.state, "scope", "session") == "session")

    @app.post("/api/projects/{name}/proposals/{pid}/approve", dependencies=[api])
    async def approve(name: str, pid: str, request: Request):
        return guard(ws.approve, name, pid, str((await request.json()).get("code", "")))

    @app.post("/api/projects/{name}/proposals/{pid}/approve-human", dependencies=[api])
    def approve_human(name: str, pid: str):
        return guard(ws.approve_human, name, pid)

    @app.post("/api/projects/{name}/proposals/{pid}/reject", dependencies=[api])
    def reject(name: str, pid: str):
        guard(ws.reject, name, pid)
        return {"ok": True}

    @app.post("/api/projects/{name}/proposals/{pid}/execute", dependencies=[api])
    async def execute(name: str, pid: str, request: Request):
        body = await request.json() if (await request.body()) else {}
        if body.get("override") and getattr(request.state, "scope", "agent") != "session":
            raise HTTPException(403, "override is human-session-only; agents cannot bypass stop-loss or attempt gates")
        override = bool(body.get("override"))
        jid = uuid.uuid4().hex[:10]
        with lock:
            jobs[jid] = {"status": "running"}

        def work():
            try:
                res = ws.execute(name, pid, override)
                with lock:
                    jobs[jid] = {"status": "done", "result": res}
            except ServiceError as e:
                with lock:
                    jobs[jid] = {"status": "error", "error": str(e), **({"budget_diff": e.diff} if hasattr(e, "diff") else {})}
            except Exception as e:   # provider/network failure: report, never crash the server
                with lock:
                    jobs[jid] = {"status": "error", "error": f"{type(e).__name__}: {e}"}
        threading.Thread(target=work, daemon=True).start()
        return {"job": jid}

    @app.get("/api/jobs/{jid}", dependencies=[api])
    def job(jid: str):
        with lock:
            return jobs.get(jid) or JSONResponse({"error": "unknown job"}, status_code=404)

    @app.post("/api/projects/{name}/shots/{shot}/approve", dependencies=[api])
    def approve_shot(name: str, shot: str):
        return guard(ws.approve_shot, name, shot)

    @app.post("/api/projects/{name}/discard", dependencies=[api])
    async def discard(name: str, request: Request):
        b = await request.json()
        return guard(ws.discard, name, b.get("rel", ""), b.get("reason", ""))

    @app.post("/api/projects/{name}/restore", dependencies=[api])
    async def restore(name: str, request: Request):
        return {"file": guard(ws.restore, name, (await request.json()).get("rel", ""))}

    @app.post("/api/projects/{name}/stills/{shot_id}/edit", dependencies=[api])
    async def still_edit(name: str, shot_id: str, request: Request):
        b = await request.json()
        return guard(ws.edit_still, name, shot_id, b.get("prompt", ""), b.get("edit_mode", "inpaint_insertion"), b.get("mask_mode", "MASK_MODE_BACKGROUND"))

    @app.post("/api/projects/{name}/clips/{shot_id}/extend", dependencies=[api])
    async def clip_extend(name: str, shot_id: str, request: Request):
        b = await request.json()
        return guard(ws.extend_clip, name, shot_id, b.get("prompt", ""), int(b.get("seconds", 5)))

    @app.get("/api/projects/{name}/spec/{kind}/{target}", dependencies=[api])
    def spec(name: str, kind: str, target: str):
        return guard(ws.spec, name, kind, target)

    @app.get("/api/projects/{name}/costs", dependencies=[api])
    def costs(name: str):
        return guard(ws.costs, name)

    @app.post("/api/projects/{name}/sync", dependencies=[api])
    def sync(name: str):
        return guard(ws.sync, name)

    @app.get("/api/projects/{name}/chat", dependencies=[api])
    def chat_history(name: str):
        return guard(ws.chat_history, name)

    @app.post("/api/projects/{name}/chat", dependencies=[api])
    async def chat_send(name: str, request: Request):
        b = await request.json()
        return guard(ws.chat_send, name, b.get("text", ""), b.get("prefs"), b.get("attachments"))

    @app.get("/api/projects/{name}/brief", dependencies=[api])
    def brief_get(name: str):
        return guard(ws.brief_get, name)

    @app.put("/api/projects/{name}/brief", dependencies=[api])
    async def brief_put(name: str, request: Request):
        return guard(ws.brief_put, name, await request.json())

    @app.get("/api/projects/{name}/todos", dependencies=[api])
    def todos(name: str):
        return guard(ws.todos, name)

    @app.post("/api/projects/{name}/todos", dependencies=[api])
    async def todo_add(name: str, request: Request):
        return guard(ws.todo_add, name, (await request.json()).get("title", ""))

    @app.post("/api/projects/{name}/todos/{tid}/toggle", dependencies=[api])
    def todo_toggle(name: str, tid: str):
        return guard(ws.todo_toggle, name, tid)

    @app.delete("/api/projects/{name}/todos/{tid}", dependencies=[api])
    def todo_remove(name: str, tid: str):
        return guard(ws.todo_remove, name, tid)

    @app.get("/api/projects/{name}/story/pending", dependencies=[api])
    def pending_story(name: str):
        return guard(ws.pending_story, name)

    @app.post("/api/projects/{name}/story/apply-pending", dependencies=[api])
    def apply_pending(name: str):
        return guard(ws.apply_pending_story, name)

    @app.post("/api/projects/{name}/story/discard-pending", dependencies=[api])
    def discard_pending(name: str):
        return guard(ws.discard_pending_story, name)

    @app.get("/api/languages", dependencies=[api])
    def languages():
        return {"languages": ws.languages()}

    @app.get("/api/ai", dependencies=[api])
    def ai_get():
        return ws.ai_settings()

    @app.put("/api/ai", dependencies=[api])
    async def ai_put(request: Request):
        return guard(ws.put_ai_settings, await request.json())

    @app.get("/api/ai/models", dependencies=[api])
    def ai_models(refresh: int = 0):
        return ws.ai_catalog(bool(refresh))

    @app.post("/api/projects/{name}/rename", dependencies=[api])
    async def rename_project(name: str, request: Request):
        return {"name": guard(ws.rename_project, name, (await request.json()).get("new", ""))}

    @app.post("/api/projects/{name}/assets/{aid}/rename", dependencies=[api])
    async def rename_asset(name: str, aid: str, request: Request):
        return guard(ws.rename_asset, name, aid, (await request.json()).get("new", ""))

    @app.post("/api/projects/{name}/shots/{sid}/rename", dependencies=[api])
    async def rename_shot(name: str, sid: str, request: Request):
        return guard(ws.rename_shot, name, sid, (await request.json()).get("new", ""))

    @app.get("/api/projects/{name}/verify", dependencies=[api])
    def verify_get(name: str):
        return guard(ws.verify_status, name)

    @app.post("/api/projects/{name}/verify", dependencies=[api])
    async def verify_post(name: str, request: Request):
        return guard(ws.verify_now, name, (await request.json()).get("scope", ""))

    @app.get("/api/projects/{name}/stills/unregistered", dependencies=[api])
    def unregistered(name: str):
        return {"files": guard(ws.unregistered_stills, name)}

    @app.post("/api/projects/{name}/stills/import", dependencies=[api])
    async def import_stills(name: str, request: Request):
        return guard(ws.import_stills, name, (await request.json()).get("items", []))

    # ---------------------------------------------------------------- providers, models, roles (settings v2)
    def auth_header(request: Request):
        # key-writing calls accept the session token ONLY in the header (never in a URL that could be logged or shared)
        if not secrets.compare_digest(request.headers.get("x-aistudio-token") or "", token):
            raise HTTPException(401, "missing or wrong session token")

    hdr = Depends(auth_header)

    @app.get("/api/setup", dependencies=[api])
    def setup_status():
        return guard(ws.setup_status)

    @app.get("/api/provider-types", dependencies=[api])
    def provider_types():
        return {"types": ws.provider_types()}

    @app.get("/api/providers", dependencies=[api])
    def providers_list():
        return guard(ws.providers_list)

    @app.post("/api/providers", dependencies=[hdr])
    async def provider_create(request: Request):
        return guard(ws.provider_create, await request.json())

    @app.patch("/api/providers/{pid}", dependencies=[api])
    async def provider_update(pid: str, request: Request):
        return guard(ws.provider_update, pid, await request.json())

    @app.delete("/api/providers/{pid}", dependencies=[api])
    def provider_delete(pid: str, force: int = 0):
        return guard(ws.provider_delete, pid, bool(force))

    @app.get("/api/providers/chatgpt/oauth/status", dependencies=[api])
    def chatgpt_status():
        return guard(ws.chatgpt_status)

    @app.post("/api/providers/chatgpt/oauth/import-codex", dependencies=[hdr])
    def chatgpt_import_codex():
        return guard(ws.chatgpt_import_codex)

    def _is_chatgpt_port_free(redirect_uri=None):
        if getattr(app.state, "chatgpt_listener", None):
            return True
        from aistudio.providers import chatgpt_auth
        import socket
        import urllib.parse
        port = urllib.parse.urlparse(redirect_uri or chatgpt_auth.REDIRECT_URI).port or 1455
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return True
            except OSError:
                return False

    @app.get("/api/providers/chatgpt/oauth/port-check", dependencies=[api])
    def chatgpt_port_check():
        from aistudio.providers import chatgpt_auth
        import urllib.parse
        port = urllib.parse.urlparse(chatgpt_auth.REDIRECT_URI).port or 1455
        free = _is_chatgpt_port_free()
        return {"port": port, "free": free, "message": f"Port {port} is free." if free else f"Port {port} is currently occupied by another program (e.g. 'codex login')."}

    @app.get("/api/providers/chatgpt/oauth/authorize", dependencies=[api])
    def chatgpt_authorize(request: Request):
        from aistudio.providers import chatgpt_auth
        import urllib.parse
        port = urllib.parse.urlparse(chatgpt_auth.REDIRECT_URI).port or 1455
        if not _is_chatgpt_port_free(chatgpt_auth.REDIRECT_URI):
            raise HTTPException(409, f"Port {port} is currently occupied by another program (e.g. 'codex login'). Please close it and try again.")
        res = guard(ws.chatgpt_authorize)
        _chatgpt_listen(res["state"], chatgpt_auth.REDIRECT_URI)
        return res

    @app.get("/api/providers/chatgpt/oauth/callback")
    def chatgpt_callback(code: str = "", state: str = "", error: str = ""):
        return _chatgpt_done(code, state, error)

    def _chatgpt_done(code, state, error=""):
        from fastapi.responses import HTMLResponse
        try:
            if error:
                raise ServiceError(error)
            ws.chatgpt_finish(code, state)
            msg, ok = "ChatGPT is connected. You can close this tab and return to AI Studio.", True
        except ServiceError as e:
            msg, ok = f"ChatGPT sign-in failed: {e}", False
        return HTMLResponse(f"<!doctype html><title>AI Studio</title><body style='font:16px system-ui;padding:3rem'><h2>{'Connected' if ok else 'Not connected'}</h2><p>{msg}</p>", 200 if ok else 400)

    def _chatgpt_stop_listener():
        _stop_chatgpt_listener(app.state)

    def _chatgpt_listen(state, redirect_uri):
        """OpenAI only accepts the redirect registered for its client (localhost:1455); serve that one callback, once, then stop."""
        import http.server
        import urllib.parse
        if getattr(app.state, "chatgpt_listener", None):
            return
        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass
            def do_GET(self):
                u = urllib.parse.urlparse(self.path)
                if u.path != urllib.parse.urlparse(redirect_uri).path:
                    self.send_error(404)
                    return
                q = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
                r = _chatgpt_done(q.get("code", ""), q.get("state", ""), q.get("error", ""))
                self.send_response(r.status_code)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(r.body)
                threading.Thread(target=_chatgpt_stop_listener, daemon=True).start()
        try:
            srv = http.server.ThreadingHTTPServer(("127.0.0.1", urllib.parse.urlparse(redirect_uri).port or 1455), H)
            srv.daemon_threads = True
        except OSError:
            raise ServiceError(f"Port {urllib.parse.urlparse(redirect_uri).port or 1455} is busy (e.g. 'codex login' running). Close it before signing in.")
        app.state.chatgpt_listener = srv
        def run():
            try:
                srv.serve_forever()
            finally:
                try:
                    srv.server_close()
                except Exception:
                    pass
                if getattr(app.state, "chatgpt_listener", None) is srv:
                    app.state.chatgpt_listener = None
        threading.Thread(target=run, daemon=True).start()
        timer = threading.Timer(900, _chatgpt_stop_listener)
        timer.daemon = True
        timer.start()
        app.state.chatgpt_timer = timer

    @app.put("/api/providers/{pid}/secret", dependencies=[hdr])
    async def provider_secret_put(pid: str, request: Request):
        return guard(ws.provider_secret_put, pid, await request.json())

    @app.delete("/api/providers/{pid}/secret", dependencies=[hdr])
    def provider_secret_delete(pid: str):
        return guard(ws.provider_secret_delete, pid)

    @app.post("/api/providers/{pid}/test", dependencies=[api])
    def provider_test(pid: str):
        return guard(ws.provider_test, pid)

    @app.get("/api/providers/{pid}/models", dependencies=[api])
    def provider_models(pid: str, refresh: int = 0):
        return guard(ws.provider_models, pid, bool(refresh))

    @app.post("/api/providers/{pid}/models", dependencies=[api])
    async def model_add(pid: str, request: Request):
        b = await request.json()
        return guard(ws.model_add, pid, b.get("id"), b.get("capability"))

    @app.get("/api/models", dependencies=[api])
    def models_all(capability: str = ""):
        return guard(ws.models_all, capability or None)

    @app.put("/api/prices/{pid}/{model:path}", dependencies=[api])
    async def price_put(pid: str, model: str, request: Request):
        return guard(ws.price_put, pid, model, await request.json())

    @app.delete("/api/prices/{pid}/{model:path}", dependencies=[api])
    def price_delete(pid: str, model: str):
        return guard(ws.price_delete, pid, model)

    @app.get("/api/roles", dependencies=[api])
    def roles_get(project: str = ""):
        return guard(ws.roles_get, project or None)

    @app.post("/api/roles/reset", dependencies=[api])
    def roles_reset():
        return guard(ws.roles_reset)

    @app.put("/api/roles/{role}", dependencies=[api])
    async def roles_put(role: str, request: Request, project: str = ""):
        b = await request.json()
        return guard(ws.roles_put, role, b.get("chain", []), b.get("policy"), project or None)

    @app.post("/api/roles/{role}/test", dependencies=[api])
    def roles_test(role: str, project: str = "", provider: str = "", model: str = ""):
        return guard(ws.roles_test, role, project or None, provider or None, model or None)

    @app.put("/api/limits", dependencies=[api])
    async def limits_put(request: Request):
        return guard(ws.limits_put, await request.json())

    @app.get("/api/projects/{name}/usage", dependencies=[api])
    def usage(name: str):
        return guard(ws.usage_by_model, name)

    # ---------------------------------------------------------------- Review & Export, export / delete project
    @app.get("/api/fonts")
    def fonts_list():
        return {"fonts": editormod.fonts_info()}

    @app.get("/api/fonts/{file}")
    def font_file(file: str):
        # public on purpose (CSS @font-face cannot send the token); only the bundled font files are reachable
        names = {fn for f in editormod.FONTS.values() for fn in [*f["weights"].values(), *f["italic"].values()]}
        if file not in names or not (editormod.FONT_DIR / file).is_file():
            raise HTTPException(404, "not found")
        return FileResponse(editormod.FONT_DIR / file, media_type="font/ttf")

    @app.get("/api/projects/{name}/edit", dependencies=[api])
    def edit_get(name: str):
        return guard(ws.edit_get, name)

    @app.put("/api/projects/{name}/edit", dependencies=[api])
    async def edit_put(name: str, request: Request):
        return {"edit": guard(ws.edit_put, name, await request.json())}

    @app.post("/api/projects/{name}/edit/export", dependencies=[api])
    def edit_export(name: str):
        guard(ws.pdir, name)
        jid = uuid.uuid4().hex[:10]
        with lock:
            jobs[jid] = {"status": "running", "progress": 0}

        def work():
            def prog(pct):
                with lock:
                    jobs[jid] = {"status": "running", "progress": round(pct, 1)}
            try:
                res = ws.edit_export(name, prog)
                with lock:
                    jobs[jid] = {"status": "done", "result": res, "progress": 100}
            except ServiceError as e:
                with lock:
                    jobs[jid] = {"status": "error", "error": str(e)}
            except Exception as e:
                with lock:
                    jobs[jid] = {"status": "error", "error": f"{type(e).__name__}: {e}"}
        threading.Thread(target=work, daemon=True).start()
        return {"job": jid}

    @app.get("/api/projects/{name}/exports", dependencies=[api])
    def exports_list(name: str):
        return {"exports": guard(ws.exports, name)}

    # ---- the timeline also leaves as Final Cut Pro XML, a CMX 3600 EDL, captions and a Canva / Google Vids bundle (all free)
    @app.get("/api/projects/{name}/edit/export-fcpxml", dependencies=[api])
    def edit_export_fcpxml(name: str):
        return Response(guard(ws.export_fcpxml, name), media_type="application/xml",
                        headers={"content-disposition": f'attachment; filename="{name}.fcpxml"'})

    @app.get("/api/projects/{name}/edit/export-edl", dependencies=[api])
    def edit_export_edl(name: str):
        return Response(guard(ws.export_edl, name), media_type="text/plain",
                        headers={"content-disposition": f'attachment; filename="{name}.edl"'})

    @app.get("/api/projects/{name}/edit/export-subtitles", dependencies=[api])
    def edit_export_subtitles(name: str, format: str = "srt"):
        body = guard(ws.export_subtitles, name, format)
        media = "application/x-subrip" if format == "srt" else "text/vtt"
        return Response(body, media_type=media, headers={"content-disposition": f'attachment; filename="{name}.{format}"'})

    @app.get("/api/projects/{name}/edit/export-bundle", dependencies=[api])
    def edit_export_bundle(name: str):
        path = guard(ws.export_bundle, name)
        return FileResponse(path, media_type="application/zip", filename=f"{name}-edit-bundle.zip",
                            background=BackgroundTask(Path(path).unlink, missing_ok=True))

    @app.post("/api/projects/{name}/audio", dependencies=[api])
    async def audio_upload(name: str, filename: str, request: Request):
        data = await request.body()
        if len(data) > 25_000_000:
            raise HTTPException(413, "file too large")
        return guard(ws.add_audio, name, filename, data)

    @app.get("/api/projects/{name}/elements", dependencies=[api])
    def elements_list(name: str):
        return {"elements": guard(ws.list_elements, name)}

    @app.post("/api/projects/{name}/elements", dependencies=[api])
    async def element_upload(name: str, filename: str, request: Request):
        data = await request.body()
        if len(data) > 25_000_000:
            raise HTTPException(413, "file too large")
        return guard(ws.add_element, name, filename, data)

    @app.get("/api/projects/{name}/export-project", dependencies=[api])
    def export_project(name: str, include_discarded: int = 0):
        path = guard(ws.export_project, name, bool(include_discarded))
        return FileResponse(path, media_type="application/zip", filename=f"{name}.zip", background=BackgroundTask(path.unlink, missing_ok=True))

    @app.delete("/api/projects/{name}", dependencies=[api])
    async def delete_project(name: str, request: Request):
        body = await request.json() if (await request.body()) else {}
        return guard(ws.delete_project, name, body.get("confirm"))

    @app.get("/api/trash", dependencies=[api])
    def trash_list():
        return {"items": ws.trash_list()}

    @app.post("/api/trash/{tid}/restore", dependencies=[api])
    async def trash_restore(tid: str, request: Request):
        body = await request.json() if (await request.body()) else {}
        return guard(ws.trash_restore, tid, body.get("as_name") or None)

    # ---------------------------------------------------------------- integrations: API keys, MCP details, the API reference
    @app.get("/api/keys", dependencies=[api])
    def keys_list():
        return {"keys": apikeys.list_keys(ws.root)}

    @app.post("/api/keys", dependencies=[hdr])
    async def keys_create(request: Request):
        try:
            rec, key = apikeys.create(ws.root, (await request.json()).get("name"))
        except apikeys.KeyError_ as e:
            raise HTTPException(400, str(e)) from None
        return {"key": key, "record": rec}

    @app.delete("/api/keys/{kid}", dependencies=[api])
    def keys_revoke(kid: str):
        try:
            apikeys.revoke(ws.root, kid)
        except apikeys.KeyError_ as e:
            raise HTTPException(404, str(e)) from None
        return {"ok": True}

    @app.get("/api/integrations", dependencies=[api])
    def integrations(request: Request):
        import sys
        from aistudio import mcp_server
        return {"mcp": {"python": sys.executable, "repo": str(REPO), "home": str(ws.root), "module": "aistudio.mcp_server"},
                "tools": [{"name": t["name"], "description": t["description"]} for t in mcp_server.tool_list()],
                "base_url": str(request.base_url).rstrip("/")}

    @app.get("/api/agents", dependencies=[api])
    def agents_list():
        return {"agents": ws.list_agents()}

    @app.post("/api/agents/run", dependencies=[api])
    async def agents_run(request: Request):
        import json
        b = await request.json()
        agent_id = b.get("agent_id", "")
        prompt = b.get("prompt", "")
        project = b.get("project")

        def event_generator():
            try:
                for chunk in ws.run_agent_stream(agent_id, prompt, project=project):
                    yield f"data: {json.dumps({'type': 'chunk', 'text': chunk})}\n\n"
                yield f"data: {json.dumps({'type': 'done'})}\n\n"
            except Exception as e:
                yield f"data: {json.dumps({'type': 'error', 'error': str(e)})}\n\n"

        return StreamingResponse(event_generator(), media_type="text/event-stream")

    @app.post("/api/agents/abort", dependencies=[api])
    async def agents_abort(request: Request):
        b = await request.json()
        agent_id = b.get("agent_id", "")
        ok = ws.abort_agent(agent_id)
        return {"ok": ok}

    @app.get("/api/docs/endpoints", dependencies=[api])
    def docs_endpoints():
        return {"endpoints": api_docs.endpoints(), "groups": api_docs.GROUPS}

    @app.get("/files/{name}/{path:path}")
    def files(name: str, path: str, request: Request):
        auth(request)
        root = ws.pdir(name).resolve()
        target = (root / path).resolve()
        if root not in target.parents or target.parent.name == "" or Path(path).parts[0] not in SERVE_DIRS \
                or target.suffix.lower() not in ALLOWED_SUFFIX or not target.is_file():
            raise HTTPException(404, "not found")
        return FileResponse(target)

    static = Path(static_dir) if static_dir else REPO / "web" / "dist"
    if static.is_dir():
        app.mount("/", StaticFiles(directory=static, html=True), name="web")
    return app


def main():
    import uvicorn
    app = create_app()
    port = int(os.environ.get("AISTUDIO_PORT", "8765"))
    ws = app.state.ws
    provs = ", ".join(f"{p['label']}: {p['status']['state']}" for p in ws.providers_list()["providers"] if p["type"] != "fake") or "none yet (add one in Settings)"
    print(f"\nAI Studio on http://127.0.0.1:{port}/?token={app.state.token}\n"
          f"  providers: {provs}"
          "\n  Keep the token private: it lets the page approve spending.\n", flush=True)
    try:
        uvicorn.run(
            app,
            host="127.0.0.1",
            port=port,
            log_level="warning",
            timeout_graceful_shutdown=1.0,
            timeout_keep_alive=3,
        )
    except (KeyboardInterrupt, SystemExit, asyncio.CancelledError):
        pass
    finally:
        _stop_chatgpt_listener(app.state)
        print("\nAI Studio stopped.", flush=True)


if __name__ == "__main__":
    main()
