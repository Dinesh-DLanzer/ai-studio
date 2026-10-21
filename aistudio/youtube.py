"""Human initiated YouTube OAuth and upload adapter (stdlib only).

OAuth credentials and tokens are stored only through ``aistudio.secrets``. The
upload transport is injectable for tests; its fake is available only in the
explicit all-test environment.
"""
import base64
import hashlib
import http.server
import json
import mimetypes
import os
import secrets as random_secrets
import socket
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path

from aistudio import publish

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
API = "https://www.googleapis.com/youtube/v3"
UPLOAD = "https://www.googleapis.com/upload/youtube/v3"
SCOPE = "https://www.googleapis.com/auth/youtube.upload https://www.googleapis.com/auth/youtube.readonly"
CHUNK = 8 * 1024 * 1024


def _b64(raw):
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def new_pkce():
    verifier = _b64(random_secrets.token_bytes(48))
    return {"verifier": verifier, "challenge": _b64(hashlib.sha256(verifier.encode()).digest()),
            "state": random_secrets.token_urlsafe(32)}


def authorize_url(pkce, redirect_uri):
    q = {"client_id": pkce["client_id"], "redirect_uri": redirect_uri, "response_type": "code", "scope": SCOPE,
         "code_challenge": pkce["challenge"], "code_challenge_method": "S256", "state": pkce["state"],
         "access_type": "offline", "prompt": "consent"}
    return AUTH_URL + "?" + urllib.parse.urlencode(q)


def _urllib_transport(method, url, headers=None, body=None):
    headers = dict(headers or {})
    if isinstance(body, dict):
        body = urllib.parse.urlencode(body).encode()
        headers.setdefault("Content-Type", "application/x-www-form-urlencoded")
    elif isinstance(body, list):
        body = json.dumps(body).encode()
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            raw = response.read()
            return {"status": response.status, "headers": dict(response.headers), "body": _decode(raw)}
    except urllib.error.HTTPError as exc:
        return {"status": exc.code, "headers": dict(exc.headers), "body": _decode(exc.read())}


def _decode(raw):
    try:
        return json.loads(raw.decode("utf-8")) if raw else {}
    except (UnicodeDecodeError, ValueError):
        return raw


def transport():
    if os.environ.get("AISTUDIO_FAKE_YOUTUBE") == "1":
        if os.environ.get("AISTUDIO_ALL_TEST") != "1":
            raise RuntimeError("fake YouTube transport requires AISTUDIO_ALL_TEST=1 test mode")
        return fake_transport
    return _urllib_transport


def fake_transport(method, url, headers=None, body=None):
    """Deterministic local transport for the opt-in web e2e mode."""
    if url == TOKEN_URL:
        return {"status": 200, "headers": {}, "body": {"access_token": "test-access-token", "refresh_token": "test-refresh-token", "expires_in": 3600}}
    if "/channels?" in url:
        return {"status": 200, "headers": {}, "body": {"items": [{"snippet": {"title": "AI Studio Test Channel"}}]}}
    if "uploadType=resumable" in url:
        return {"status": 200, "headers": {"Location": "https://www.googleapis.com/upload/youtube/v3/session-test"}, "body": {}}
    if "session-test" in url:
        return {"status": 200, "headers": {}, "body": {"id": "test-video-id"}}
    if "/thumbnails/set?" in url:
        return {"status": 200, "headers": {}, "body": {}}
    return {"status": 404, "headers": {}, "body": {}}


def _call(t, method, url, headers=None, body=None):
    try:
        return (t or transport())(method, url, headers=headers or {}, body=body)
    except Exception:
        # urllib and custom transports may include bearer headers, authorization codes,
        # or resumable session URLs in exception strings. Never forward them.
        raise ValueError("YouTube network request failed; check the connection and try again") from None


def save_client(secret_store, client_id, client_secret):
    if not isinstance(client_id, str) or not client_id.strip() or not isinstance(client_secret, str) or not client_secret.strip():
        raise ValueError("client id and client secret are required")
    old = secret_store.get("youtube")
    same_client = old.get("client_id") == client_id.strip() and old.get("client_secret") == client_secret.strip()
    kept = {k: v for k, v in old.items() if k in ("access_token", "refresh_token", "expires_at") } if same_client else {}
    secret_store.set("youtube", {**kept, "client_id": client_id.strip(), "client_secret": client_secret.strip()})
    return {"saved": True}


def _token_result(resp, old=None):
    body = resp.get("body") if isinstance(resp, dict) and "body" in resp else resp
    if not isinstance(body, dict) or not body.get("access_token"):
        raise ValueError("YouTube sign-in failed; check the OAuth client and try again")
    old = old or {}
    refresh = body.get("refresh_token") or old.get("refresh_token")
    if not refresh:
        raise ValueError("YouTube did not return a refresh token; disconnect and connect again")
    return {**old, "access_token": str(body["access_token"]), "refresh_token": str(refresh),
            "expires_at": str(int(time.time()) + int(body.get("expires_in", 3600)))}


def finish_oauth(secret_store, call, pending, code, state):
    if not state or not secrets_compare(state, pending.get("state", "")):
        raise ValueError("OAuth state verification failed")
    current = secret_store.get("youtube")
    if not current.get("client_id") or not current.get("client_secret"):
        raise ValueError("save the YouTube OAuth client before connecting")
    resp = _call(call, "POST", TOKEN_URL, body={"grant_type": "authorization_code", "code": code,
                 "client_id": current["client_id"], "client_secret": current["client_secret"],
                 "redirect_uri": pending["redirect_uri"], "code_verifier": pending["verifier"]})
    fresh = _token_result(resp)
    secret_store.set("youtube", {**current, **fresh})
    return {"connected": True}


def secrets_compare(a, b):
    import hmac
    return hmac.compare_digest(str(a), str(b))


def valid_tokens(secret_store, call=None, now=None):
    secret = secret_store.get("youtube")
    if not secret.get("refresh_token"):
        raise ValueError("Connect a YouTube account first")
    if int(secret.get("expires_at") or 0) > (now if now is not None else time.time()) + 60:
        return secret
    resp = _call(call, "POST", TOKEN_URL, body={"grant_type": "refresh_token", "refresh_token": secret["refresh_token"],
                 "client_id": secret.get("client_id", ""), "client_secret": secret.get("client_secret", "")})
    fresh = _token_result(resp, secret)
    secret_store.set("youtube", fresh)
    return fresh


def _api_json(secret_store, call, url, body=None, method="GET"):
    tokens = valid_tokens(secret_store, call)
    headers = {"Authorization": "Bearer " + tokens["access_token"]}
    if body is not None:
        headers["Content-Type"] = "application/json; charset=UTF-8"
        body = json.dumps(body).encode()
    resp = _call(call, method, url, headers=headers, body=body)
    if not isinstance(resp, dict) or int(resp.get("status", 200)) >= 400:
        raise ValueError(_safe_provider_error(resp))
    return resp.get("body", resp)


def _safe_provider_error(resp):
    # Never include provider bodies/URLs: they can echo credentials or upload session IDs.
    status = resp.get("status") if isinstance(resp, dict) else "network"
    return "YouTube request failed (HTTP %s); check quota, permissions, and account status" % status


def status(secret_store, call=None):
    s = secret_store.get("youtube")
    connected = bool(s.get("refresh_token"))
    out = {"connected": connected, "expires": int(s.get("expires_at") or 0) or None}
    if connected:
        try:
            body = _api_json(secret_store, call, API + "/channels?part=snippet&mine=true")
            items = body.get("items") or []
            title = (items[0].get("snippet") or {}).get("title") if items else None
            if title:
                out["channel_title"] = title
        except Exception:
            pass
    return out


def start_oauth(secret_store, call=None, timeout=300):
    s = secret_store.get("youtube")
    if not s.get("client_id") or not s.get("client_secret"):
        raise ValueError("save the YouTube OAuth client id and secret first")
    pkce = {**new_pkce(), "client_id": s["client_id"]}
    listener = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _OAuthHandler)
    listener.timeout = 1
    port = listener.server_address[1]
    redirect = f"http://127.0.0.1:{port}/"
    pending = {"state": pkce["state"], "verifier": pkce["verifier"], "redirect_uri": redirect}
    listener.pending = pending
    listener.secret_store = secret_store
    listener.call = call
    listener.deadline = time.monotonic() + timeout
    thread = threading.Thread(target=_serve_once, args=(listener,), daemon=True, name="youtube-oauth")
    thread.start()
    return {"url": authorize_url(pkce, redirect), "expires_in": timeout}


class _OAuthHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        params = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
        code, state = (params.get("code") or [""])[0], (params.get("state") or [""])[0]
        try:
            if params.get("error"):
                raise ValueError("YouTube sign-in was cancelled")
            finish_oauth(self.server.secret_store, self.server.call, self.server.pending, code, state)
            content = b"YouTube connected. You can close this tab and return to AI Studio."
            status = 200
        except Exception:
            content = b"YouTube connection failed. Return to AI Studio and try again."
            status = 400
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)
        self.server.done = True

    def log_message(self, *_args):
        return


def _serve_once(server):
    try:
        while not getattr(server, "done", False) and time.monotonic() < server.deadline:
            server.handle_request()
    finally:
        server.server_close()


def _project_file(project_dir, rel):
    root = Path(project_dir).resolve()
    path = (root / rel).resolve()
    if root not in path.parents or not path.is_file():
        raise ValueError("export file must exist inside the project")
    return path


def check_consent(project_dir):
    """Refuse when unconsented real-person assets or marked file SHAs appear in images or timeline."""
    from aistudio import consent
    p = Path(project_dir)
    images_file = p / "images.json"
    if images_file.is_file():
        try:
            images_doc = json.loads(images_file.read_text(encoding="utf-8"))
            ids = [i["id"] for i in images_doc.get("images", []) if isinstance(i, dict) and i.get("real_person")]
            if ids:
                consent.require_assets(p, images_doc, ids)
        except Exception as se:
            raise ValueError(f"real person consent required before YouTube upload: {se}") from se
    marked = consent.real_person_shas(p)
    if marked:
        from aistudio.domain.common import _sha
        edit_file = p / "edit.json"
        if edit_file.is_file():
            try:
                edit_doc = json.loads(edit_file.read_text(encoding="utf-8"))
                shas_to_check = []
                for track in edit_doc.get("tracks", {}).values():
                    if isinstance(track, list):
                        for item in track:
                            rel = item.get("file") or item.get("source") or item.get("path")
                            if rel:
                                fp = p / rel
                                if fp.is_file():
                                    h = _sha(fp)
                                    if h in marked:
                                        shas_to_check.append(h)
                if shas_to_check:
                    consent.require_shas(p, shas_to_check)
            except Exception as se:
                raise ValueError(f"real person consent required before YouTube upload: {se}") from se


def preview(project_dir, preset, preflight=None, privacy="private", channel_title=""):
    if not channel_title:
        raise ValueError("could not verify the connected YouTube channel; reconnect and try again")
    root = Path(project_dir).resolve()
    check_consent(root)
    doc = publish.get(_ProjectView(root), root.name)
    if doc["platform"] != "youtube" or doc["status"] != "exported":
        raise ValueError("YouTube upload requires saved, exported YouTube metadata")
    if doc.get("preset_id") != preset:
        raise ValueError("choose the exported preset file shown in publish metadata")
    errors = [i for i in (preflight or []) if i.get("level") == "error" or i.get("severity") == "error"]
    if errors:
        raise ValueError("YouTube upload blocked: preflight has errors")
    rel = Path("exports") / preset / "platform" / (root.name + ".mp4")
    file_path = _project_file(root, rel)
    digest = hashlib.sha256()
    with file_path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(block)

    thumb_sha = ""
    thumb_rel = doc.get("thumbnail", "")
    if thumb_rel:
        try:
            thumb_file = _project_file(root, thumb_rel)
            if thumb_file.is_file():
                td = hashlib.sha256()
                with thumb_file.open("rb") as tf:
                    for blk in iter(lambda: tf.read(1024 * 1024), b""):
                        td.update(blk)
                thumb_sha = td.hexdigest()
        except Exception:
            pass

    return {"file": rel.as_posix(), "size": file_path.stat().st_size, "sha256": digest.hexdigest(),
            "title": doc["title"], "description": doc["description"], "privacy": privacy if privacy in ("private", "unlisted", "public") else "private",
            "tags": doc.get("tags") or [t.lstrip("#") for t in doc.get("hashtags", [])], "category_id": doc.get("category_id", "22"),
            "thumbnail": doc.get("thumbnail", ""), "thumbnail_sha256": thumb_sha,
            "channel_title": channel_title, "preset": preset}


def run_preflight(project_dir, preset):
    from aistudio import delivery, editor
    root = Path(project_dir).resolve()
    doc = publish.get(_ProjectView(root), root.name)
    if doc.get("preset_id") != preset:
        raise ValueError("choose the preset saved in publish metadata")
    path = _project_file(root, Path("exports") / preset / "platform" / (root.name + ".mp4"))
    edit = editor.clean(json.loads((root / "edit.json").read_text(encoding="utf-8")))
    probe = editor.probe(path)
    return delivery.preflight(delivery.get_preset(preset), probe or {}, edit)


class _ProjectView:
    def __init__(self, root): self.root = root
    def pdir(self, project): return self.root


def _upload_json(secret_store, call, url, payload):
    tokens = valid_tokens(secret_store, call)
    headers = {"Authorization": "Bearer " + tokens["access_token"], "Content-Type": "application/json; charset=UTF-8"}
    return _call(call, "POST", url, headers=headers, body=json.dumps(payload).encode())


def upload_file(secret_store, call, path, metadata, privacy="private", progress=None, file_size=None, filename=None):
    if hasattr(path, "read") and hasattr(path, "seek"):
        f = path
        size = file_size if file_size is not None else 0
        name = filename or "video.mp4"
        close_f = False
    else:
        p = Path(path)
        size = p.stat().st_size
        name = p.name
        f = p.open("rb")
        close_f = True
    if privacy not in ("private", "unlisted", "public"):
        privacy = "private"
    tags = [str(t).lstrip("#") for t in (metadata.get("tags") or metadata.get("hashtags") or [])]
    snippet = {"title": metadata.get("title", ""), "description": metadata.get("description", ""), "tags": tags,
               "categoryId": str(metadata.get("category_id") or "22")}
    body = {"snippet": snippet, "status": {"privacyStatus": privacy}}
    mime = mimetypes.guess_type(name)[0] or "video/mp4"
    init_url = UPLOAD + "/videos?uploadType=resumable&part=snippet,status"
    response = _upload_json(secret_store, call, init_url, body)
    if int(response.get("status", 200)) >= 400:
        if close_f:
            f.close()
        raise ValueError(_safe_provider_error(response))
    headers = response.get("headers") or {}
    session_url = headers.get("Location") or headers.get("location")
    parsed_session = urllib.parse.urlsplit(session_url or "")
    if not session_url or parsed_session.scheme != "https" or parsed_session.hostname != "www.googleapis.com" or not parsed_session.path.startswith("/upload/"):
        if close_f:
            f.close()
        raise ValueError("YouTube did not create a resumable upload session")
    offset = 0
    try:
        while offset < size:
            f.seek(offset)
            chunk = f.read(min(CHUNK, size - offset))
            end = offset + len(chunk) - 1
            tokens = valid_tokens(secret_store, call)
            headers = {"Authorization": "Bearer " + tokens["access_token"], "Content-Type": mime,
                       "Content-Length": str(len(chunk)), "Content-Range": f"bytes {offset}-{end}/{size}"}
            try:
                resp = _call(call, "PUT", session_url, headers=headers, body=chunk)
            except Exception:
                # Query the session after a transport interruption. The server's Range is the source of truth.
                tokens = valid_tokens(secret_store, call)
                query = _call(call, "PUT", session_url, headers={"Authorization": "Bearer " + tokens["access_token"],
                              "Content-Length": "0", "Content-Range": f"bytes */{size}"}, body=b"")
                resp = query
            code = int(resp.get("status", 200))
            if code == 308:
                ran = (resp.get("headers") or {}).get("Range", "")
                if ran:
                    offset = int(ran.rsplit("-", 1)[1]) + 1
                elif end >= offset:
                    offset = end + 1
                else:
                    raise ValueError("YouTube upload made no progress")
                if progress:
                    progress(min(99, offset * 100 / max(size, 1)))
                continue
            if code >= 400:
                raise ValueError(_safe_provider_error(resp))
            data = resp.get("body") or {}
            video_id = data.get("id") if isinstance(data, dict) else None
            if not video_id:
                raise ValueError("YouTube accepted the upload but did not return its video id; check YouTube Studio before retrying")
            if progress:
                try:
                    progress(100)
                except Exception:
                    # The provider has accepted the video; preserve and return its ID even if
                    # a late cancel request reached the job at the same time.
                    pass
            return {"video_id": video_id, "url": "https://www.youtube.com/watch?v=" + video_id}
        raise ValueError("YouTube upload ended without a video id")
    finally:
        if close_f:
            f.close()


def queue_upload(ws, project, preset, privacy="private", confirm_title="", preflight=None, runner=None, sha256="", title=""):
    pdir = ws.pdir(project)
    check_consent(pdir)
    doc = publish.get(ws, project)
    if not (doc.get("title") or "").strip():
        raise ValueError("set a title in publish.json before uploading")
    if confirm_title and confirm_title != doc.get("title"):
        raise ValueError("typed title does not match publish.json")
    if title and title != doc.get("title"):
        raise ValueError("title does not match publish.json")
    state = status(ws.secrets)
    if not state.get("connected"):
        raise ValueError("connect a YouTube account in Settings before uploading")
    info = preview(pdir, preset, preflight=preflight, privacy=privacy, channel_title=state.get("channel_title", ""))
    if sha256 and sha256 != info["sha256"]:
        raise ValueError("previewed sha256 does not match export file")
    if privacy and privacy != info["privacy"]:
        raise ValueError("privacy does not match preview")
    payload = {**info, "privacy": info["privacy"]}
    if runner is None:
        raise ValueError("YouTube uploads require the durable job ledger")
    from . import jobs
    for old in jobs.list_jobs(runner.root, project=project, limit=500):    # one upload per exact file: a double click must not post twice
        p = old.get("payload") or {}
        if old["kind"] == "publish_upload" and old["target"] == preset and p.get("sha256") == info["sha256"] \
                and old["state"] in ("queued", "running", "provider_pending", "completed", "needs_sync"):
            raise ValueError("this exact export was already uploaded or is uploading; check the job list before sending it again")
    job = runner.submit(project, "publish_upload", target=preset, actor="local", payload=payload)
    return {"job": job["id"], "file": info["file"], "size": info["size"], "sha256": info["sha256"], "title": info["title"], "privacy": info["privacy"]}


def upload_video(ws, project, preset, privacy="private", confirm_title="", preflight=None, runner=None, sha256="", title=""):
    """Queue one reviewed preset export in the durable, non-restartable upload ledger."""
    return queue_upload(ws, project, preset, privacy, confirm_title, preflight, runner, sha256=sha256, title=title)


def upload_job(secret_store, project_dir, job, progress, call=None):
    payload = job["payload"]
    path = _project_file(project_dir, payload["file"])
    check_consent(project_dir)
    f = path.open("rb")
    try:
        digest = hashlib.sha256()
        for block in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(block)
        if digest.hexdigest() != payload["sha256"]:
            raise ValueError("export changed after confirmation; export and review it again")
        f.seek(0)
        # The reviewed metadata is frozen into the human-started job. A later edit to
        # publish.json cannot silently change what this upload sends to YouTube.
        meta = {"title": payload["title"], "description": payload.get("description", ""),
                "tags": payload.get("tags", []), "category_id": payload.get("category_id", "22"),
                "thumbnail": payload.get("thumbnail", "")}
        if meta["thumbnail"] and payload.get("thumbnail_sha256"):
            thumb = _project_file(project_dir, meta["thumbnail"])
            t_digest = hashlib.sha256()
            with thumb.open("rb") as tf:
                for block in iter(lambda: tf.read(1024 * 1024), b""):
                    t_digest.update(block)
            if t_digest.hexdigest() != payload["thumbnail_sha256"]:
                raise ValueError("thumbnail changed after confirmation; review and queue again")
        result = upload_file(secret_store, call, f, meta, payload.get("privacy", "private"), progress,
                             file_size=path.stat().st_size, filename=path.name)
    finally:
        f.close()

    if meta["thumbnail"]:
        try:
            thumb = _project_file(project_dir, meta["thumbnail"])
            if thumb.stat().st_size > 50 * 1024 * 1024:
                raise ValueError("thumbnail exceeds YouTube's 50 MB limit")
            mime = mimetypes.guess_type(thumb.name)[0]
            if mime not in ("image/png", "image/jpeg"):
                raise ValueError("thumbnail must be a PNG or JPEG")
            if payload.get("thumbnail_sha256"):
                t_digest = hashlib.sha256()
                with thumb.open("rb") as tf:
                    for block in iter(lambda: tf.read(1024 * 1024), b""):
                        t_digest.update(block)
                if t_digest.hexdigest() != payload["thumbnail_sha256"]:
                    raise ValueError("thumbnail changed after confirmation; review and queue again")
            tokens = valid_tokens(secret_store, call)
            url = UPLOAD + "/thumbnails/set?videoId=" + urllib.parse.quote(result["video_id"])
            resp = _call(call, "POST", url, headers={"Authorization": "Bearer " + tokens["access_token"], "Content-Type": mime}, body=thumb.read_bytes())
            if int(resp.get("status", 200)) >= 400:
                raise ValueError(_safe_provider_error(resp))
        except Exception as exc:
            if "thumbnail changed" in str(exc):
                raise
            result["thumbnail_error"] = "video uploaded, but its thumbnail could not be set; check the video ID before retrying"
    return result


def disconnect(secret_store):
    secret_store.delete("youtube")
    return {"connected": False}
