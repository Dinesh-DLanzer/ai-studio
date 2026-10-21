"""ComfyUI: the user's own local image and video engine.  Standard library only.

ENDPOINTS (read out of the ComfyUI server source, master, 2026-10-20; there is no API key, the server is the user's own):
  GET  /system_stats                     -> {"system": {...}, "devices": [...]}
  POST /prompt  {"prompt": <workflow>, "client_id": ...}
                                        -> {"prompt_id": ..., "number": ..., "node_errors": {}}
                                           400 + {"error": {...}, "node_errors": {...}} when the workflow is invalid
  GET  /history/{prompt_id}              -> {prompt_id: {"outputs": {node: {"images": [{"filename", "subfolder", "type"}]}},
                                                        "status": {"status_str": "success"|"error", "completed": bool, "messages": [...]}}}}
                                           {} while the prompt is still running
  GET  /view?filename=&subfolder=&type=  -> the file bytes (404 when the file is gone)
  GET  /queue                            -> {"queue_running": [[number, prompt_id, ...]], "queue_pending": [...]}
  POST /interrupt {"prompt_id": ...}     -> stops the running prompt (a body without prompt_id interrupts everything)
  POST /queue {"delete": [prompt_id]}     -> drops a prompt that is still waiting

Subclass of aistudio.providers.base.Adapter (read its docstring first).
  type = "comfyui" ; capabilities = {"image","video"} ; default_base_url = "http://127.0.0.1:8188" ; the secret has no fields.
  The model id is the id of a workflow manifest: the workflow lives in <workflows_dir>/<id> (workflow_api.json + manifest.json)
  and the manifest says which node every AI Studio input goes to (see comfyui_manifest.py).  The workflows_dir comes from the
  constructor, from conn["workflows_dir"] or from opts["workflows_dir"]; a workflow can also be handed over directly with
  opts["workflow"] / opts["manifest"].
  Costs are None: the engine is local and free, the ledger still logs the run.

list_models(): the workflow manifests that are installed: [{"id","name","capability"}] (video for the video tasks, image for the rest).
test(): GET /system_stats -> {"ok": True, "message": "Connected successfully (ComfyUI <version>)"} or {"ok": False, "message": scrub(error)[:200]}.
  Never raises.
submit(workflow): POST /prompt -> the prompt id; a workflow the server refuses raises Rejected.
wait(prompt_id): GET /history/{prompt_id} until the run is done (self.sleep between the polls, like ReplicateAdapter).
run(workflow): submit + wait + fetch every output file with GET /view -> {"prompt_id", "files": [{filename, subfolder, type, bytes}], "outputs"}.
image(model, prompt, refs=(), aspect_ratio="9:16", opts=None): the manifest maps the values, the workflow runs and the first image
  file comes back: {"bytes", "usage": {}, "cost": None, "model"}.
video_submit/video_poll/video_download: the same workflow driven as a job: submit -> poll /history -> download the video file.
queue_position(prompt_id): GET /queue -> 1 for the running prompt, 2 for the first waiting one, None when it is not queued.
cancel(prompt_id): POST /interrupt (running) and POST /queue {"delete": [...]} (waiting).

IMAGES: ComfyUI reads images from its own input folder, so an image input is the NAME of the file inside that folder, not the
bytes: the adapter writes the file name.  Uploading a file needs a multipart request, which the shared transport does not do yet.
"""
import random
import time
import urllib.parse
import uuid
from pathlib import Path

from aistudio.providers.adapters.comfyui_manifest import (MANIFEST_FILE, apply_inputs, list_manifests,
                                                          load_manifest)
from aistudio.providers.base import Adapter, NotFound, Rejected, Retryable, scrub

IMAGE_EXT = (".png", ".jpg", ".jpeg", ".webp", ".bmp")
VIDEO_EXT = (".mp4", ".webm", ".mov", ".mkv", ".m4v", ".gif")


def _pick(files, exts):
    """The first file whose name ends with one of `exts`, else None."""
    for f in files:
        if str(f.get("filename") or "").lower().endswith(exts):
            return f
    return None


def _queue_id(item):
    """A queue entry is (number, prompt_id, prompt, extra_data, ...)."""
    if isinstance(item, (list, tuple)) and len(item) > 1:
        return str(item[1])
    return str(item)


def _error_text(err, depth=0):
    """A short, readable message out of whatever shape the server used for the error."""
    if err is None:
        return ""
    if isinstance(err, str):
        return err.strip()[:300]
    if isinstance(err, (list, tuple)):
        parts = []
        for item in err:
            if isinstance(item, (list, tuple)) and len(item) == 2 and isinstance(item[1], dict):
                parts.append(_error_text(item[1], depth + 1))
            else:
                parts.append(_error_text(item, depth + 1))
        return "; ".join(p for p in parts if p)[:300]
    if isinstance(err, dict):
        if depth > 4:
            return ""
        for key in ("message", "exception_message", "details"):
            value = err.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()[:300]
        for key in ("errors", "node_errors"):
            value = err.get(key)
            if value:
                text = _error_text(value, depth + 1)
                if text:
                    return text
        parts = [_error_text(v, depth + 1) for v in err.values()]
        return "; ".join(p for p in parts if p)[:300]
    return str(err)[:300]


class ComfyUIAdapter(Adapter):
    type = "comfyui"
    capabilities = frozenset({"image", "video"})
    default_base_url = "http://127.0.0.1:8188"

    def __init__(self, conn, transport=None, sleep=time.sleep, workflows_dir=None):
        super().__init__(conn, transport)
        self.sleep = sleep
        self.workflows_dir = workflows_dir or conn.get("workflows_dir") or ""
        self.client_id = uuid.uuid4().hex

    # ---------------------------------------------------------------- models
    def list_models(self):
        out = []
        for m in list_manifests(self.workflows_dir):
            out.append({"id": m["id"], "name": m["id"],
                        "capability": "video" if "video" in m["task"] else "image"})
        return out

    def test(self):
        try:
            body = self.transport("GET", self.base_url + "/system_stats")
        except Exception as e:
            return {"ok": False, "message": scrub(e, self.secret)[:200]}
        version = ""
        if isinstance(body, dict):
            version = (body.get("system") or {}).get("comfyui_version") or ""
        message = "Connected successfully"
        if version:
            message += " (ComfyUI %s)" % version
        return {"ok": True, "message": message}

    # ---------------------------------------------------------------- the API
    def submit(self, workflow):
        """POST /prompt -> the prompt id of the queued workflow."""
        body = self.transport("POST", self.base_url + "/prompt",
                              body={"prompt": workflow, "client_id": self.client_id})
        if isinstance(body, dict) and body.get("error"):
            text = _error_text(body.get("error"))
            nodes = _error_text(body.get("node_errors"))
            raise Rejected("; ".join(p for p in (text, nodes) if p)[:300] or "ComfyUI refused the workflow")
        prompt_id = body.get("prompt_id") if isinstance(body, dict) else None
        if not prompt_id:
            raise Retryable("ComfyUI did not return a prompt id")
        return prompt_id

    def history(self, prompt_id):
        """GET /history/{prompt_id} -> the history entry of the run ({} when it is not there yet)."""
        body = self.transport("GET", self.base_url + "/history/" + str(prompt_id))
        if not isinstance(body, dict):
            return {}
        entry = body.get(str(prompt_id))
        return entry if isinstance(entry, dict) else {}

    @staticmethod
    def files_in(entry):
        """The output files of a history entry: [{"filename", "subfolder", "type"}]."""
        out = []
        for node in ((entry or {}).get("outputs") or {}).values():
            if not isinstance(node, dict):
                continue
            for group in node.values():
                if not isinstance(group, list):
                    continue
                for item in group:
                    if isinstance(item, dict) and item.get("filename"):
                        out.append({"filename": item["filename"],
                                    "subfolder": item.get("subfolder") or "",
                                    "type": item.get("type") or "output"})
        return out

    def fetch(self, filename, subfolder="", type_="output"):
        """GET /view -> the bytes of one file of the ComfyUI output folder."""
        query = urllib.parse.urlencode({"filename": filename, "subfolder": subfolder or "", "type": type_ or "output"})
        return self.transport("GET", self.base_url + "/view?" + query, raw=True)

    def wait(self, prompt_id, opts=None):
        """GET /history/{prompt_id} until the run is done.  Returns the history entry."""
        opts = opts or {}
        max_polls = int(opts.get("max_polls", 60))
        poll_seconds = opts.get("poll_seconds", 2)
        for i in range(max_polls):
            if i:
                self.sleep(poll_seconds)
            entry = self.history(prompt_id)
            if not entry:
                continue
            status = entry.get("status") or {}
            if status.get("status_str") == "error":
                raise Rejected(_error_text(status.get("messages")) or "the ComfyUI workflow failed")
            if entry.get("outputs"):
                return entry
            if status.get("completed"):
                return entry
        raise Retryable("timed out waiting for ComfyUI")

    def run(self, workflow, opts=None):
        """Run a workflow: submit it, wait for it and fetch its output files."""
        opts = opts or {}
        prompt_id = self.submit(workflow)
        entry = self.wait(prompt_id, opts)
        files = []
        for f in self.files_in(entry):
            f = dict(f)
            f["bytes"] = self.fetch(f["filename"], f["subfolder"], f["type"])
            files.append(f)
        return {"prompt_id": prompt_id, "files": files, "outputs": entry.get("outputs") or {}}

    def queue_position(self, prompt_id):
        """GET /queue -> 1 for the running prompt, 2 for the first waiting one, None when it is not queued."""
        body = self.transport("GET", self.base_url + "/queue")
        if not isinstance(body, dict):
            return None
        running = body.get("queue_running") or []
        pending = body.get("queue_pending") or []
        for i, item in enumerate(running, 1):
            if _queue_id(item) == str(prompt_id):
                return i
        for i, item in enumerate(pending, len(running) + 1):
            if _queue_id(item) == str(prompt_id):
                return i
        return None

    def cancel(self, prompt_id=None):
        """POST /interrupt (running) and POST /queue {"delete": [...]} (still waiting)."""
        body = {"prompt_id": str(prompt_id)} if prompt_id else {}
        self.transport("POST", self.base_url + "/interrupt", body=body)
        if prompt_id:
            self.transport("POST", self.base_url + "/queue", body={"delete": [str(prompt_id)]})
        return {"cancelled": bool(prompt_id)}

    # ---------------------------------------------------------------- the workflows
    def _workflow(self, model, opts=None):
        """The manifest and the workflow of a model id (a manifest id)."""
        opts = opts or {}
        manifest = opts.get("manifest")
        workflow = opts.get("workflow")
        if workflow is None and isinstance(manifest, dict):
            workflow = manifest.get("workflow")
        if manifest is None or workflow is None:
            root = opts.get("workflows_dir") or self.workflows_dir
            if not root:
                raise NotFound("no ComfyUI workflow folder is configured for %r" % model)
            folder = Path(root) / str(model)
            if not (folder / MANIFEST_FILE).is_file():
                raise NotFound("no ComfyUI workflow named %r in %s" % (model, root))
            try:
                loaded = load_manifest(folder)
            except ValueError as e:
                raise Rejected("the ComfyUI workflow %r is not usable: %s" % (model, e))
            manifest = manifest if manifest is not None else loaded
            workflow = workflow if workflow is not None else loaded["workflow"]
        return manifest, workflow

    def _values(self, base, refs, manifest):
        """The AI Studio inputs the manifest can take, ready to be written into the workflow."""
        values = {k: v for k, v in (base or {}).items() if v is not None}
        if refs:
            values["start_frame"] = Path(str(refs[0])).name
            if len(refs) > 1:
                values["end_frame"] = Path(str(refs[1])).name
        if "seed" in (manifest.get("inputs") or {}) and values.get("seed") is None:
            values["seed"] = random.randrange(0, 2 ** 32)
        return values

    # ---------------------------------------------------------------- the generation
    def image(self, model, prompt, refs=(), aspect_ratio="9:16", opts=None):
        opts = opts or {}
        manifest, workflow = self._workflow(model, opts)
        values = self._values({"prompt": prompt, "negative_prompt": opts.get("negative_prompt"),
                                "seed": opts.get("seed"), "seconds": opts.get("seconds"),
                                "resolution": opts.get("resolution"), "aspect_ratio": aspect_ratio},
                               list(refs or []), manifest)
        out = self.run(apply_inputs(workflow, manifest, values), opts)
        files = out["files"]
        pick = _pick(files, IMAGE_EXT) or (files[0] if files else None)
        if not pick:
            raise Retryable("ComfyUI produced no image")
        return {"bytes": pick["bytes"], "usage": {}, "cost": None, "model": model}

    def video_submit(self, model, req):
        req = req or {}
        manifest, workflow = self._workflow(model, req.get("opts"))
        refs = [req["first_frame"]] if req.get("first_frame") else []
        values = self._values({"prompt": req.get("prompt"), "negative_prompt": req.get("negative_prompt"),
                                "seed": req.get("seed"), "seconds": req.get("seconds"),
                                "resolution": req.get("resolution"), "aspect_ratio": req.get("aspect_ratio")},
                               refs, manifest)
        prompt_id = self.submit(apply_inputs(workflow, manifest, values))
        return {"job_id": prompt_id, "model": model}

    def video_poll(self, job):
        entry = self.history(job["job_id"])
        status = entry.get("status") or {}
        if status.get("status_str") == "error":
            return {"status": "failed", "error": _error_text(status.get("messages")) or "generation failed",
                    "cost": None}
        if _pick(self.files_in(entry), VIDEO_EXT):
            return {"status": "done", "error": None, "cost": None}
        if status.get("completed"):
            return {"status": "failed", "error": "ComfyUI produced no video", "cost": None}
        return {"status": "pending", "error": None, "cost": None}

    def video_download(self, job):
        entry = self.history(job["job_id"])
        status = entry.get("status") or {}
        if status.get("status_str") == "error":
            raise Rejected(_error_text(status.get("messages")) or "generation failed")
        pick = _pick(self.files_in(entry), VIDEO_EXT)
        if not pick:
            raise Retryable("not finished")
        return self.fetch(pick["filename"], pick["subfolder"], pick["type"])
