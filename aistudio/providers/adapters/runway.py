"""Runway (Gen-3/Gen-4 video).  Standard library only.

NOTE: shapes are from Runway's public API and must be re-checked against the live docs before release.
Subclass of aistudio.providers.base.Adapter (read its docstring first).
  type = "runway" ; capabilities = {"video"} ; default_base_url = "https://api.dev.runwayml.com/v1"
  Headers on EVERY request: {"Authorization": "Bearer " + api_key, "X-Runway-Version": "2024-11-06"}.  URLs are base_url + path.

list_models(): there is no list endpoint. Return a fixed list: [{"id":"gen4_turbo","name":"Gen-4 Turbo","capability":"video"},
  {"id":"gen3a_turbo","name":"Gen-3 Alpha Turbo","capability":"video"}].
test(): override: GET /organization ; ok True with message "Connected successfully" on success, else {"ok": False, "message": scrub(error)[:200]}
  (never raises; scrub is in aistudio.providers.base).

video_submit(model, req): if req.get("first_frame") (a path): POST /image_to_video body
  {"model": model, "promptImage": data_url(path), "promptText": req["prompt"], "ratio": RATIO, "duration": int(req["seconds"])}
  else POST /text_to_video with the same body but WITHOUT promptImage. RATIO = "720:1280" for aspect_ratio "9:16", "1280:720" for "16:9",
  "960:960" for "1:1"; any other value is passed through unchanged. Response {"id": ...} -> {"job_id": id, "model": model}.
video_poll(job): GET /tasks/{job_id} -> status in PENDING/RUNNING/THROTTLED => {"status":"pending","error":None,"cost":None};
  SUCCEEDED => {"status":"done","error":None,"cost":None}; FAILED or CANCELLED => {"status":"failed","error": body.get("failure") or "generation failed","cost":None}.
video_download(job): GET /tasks/{job_id}; if status is not SUCCEEDED or output is empty raise Retryable("not finished");
  else self.transport("GET", output[0], raw=True) WITHOUT auth headers (signed URL) and return the bytes.
"""
from aistudio.providers.base import Adapter, ProviderError, Rejected, Retryable, data_url, scrub

RATIOS = {"9:16": "720:1280", "16:9": "1280:720", "1:1": "960:960"}
MODELS = [
    {"id": "gen4_turbo", "name": "Gen-4 Turbo", "capability": "video"},
    {"id": "gen3a_turbo", "name": "Gen-3 Alpha Turbo", "capability": "video"},
]


class RunwayAdapter(Adapter):
    type = "runway"
    capabilities = frozenset({"video"})
    request_features = frozenset({"end_frame"})
    default_base_url = "https://api.dev.runwayml.com/v1"

    @staticmethod
    def preflight(model, req):
        if req.get("last_frame"):
            if not req.get("first_frame"):
                return "Runway needs a start frame to use an end frame"
            if model != "gen4_turbo":
                return "end-frame control is verified only for gen4_turbo"
        if req.get("refs"):
            return "Runway video reference images are not verified for this model"
        if req.get("camera_native"):
            return "Runway native camera parameters are not verified for this model; put camera wording in the prompt"
        return None

    def _headers(self):
        return {
            "Authorization": "Bearer " + self.secret.get("api_key", ""),
            "X-Runway-Version": "2024-11-06",
        }

    def _get(self, path):
        return self.transport("GET", self.base_url + path, headers=self._headers())

    def list_models(self):
        return [dict(m) for m in MODELS]

    def test(self):
        try:
            self._get("/organization")
        except ProviderError as e:
            return {"ok": False, "message": scrub(e, self.secret)[:200]}
        return {"ok": True, "message": "Connected successfully"}

    def video_submit(self, model, req):
        problem = self.preflight(model, req)
        if problem:
            raise Rejected(problem)
        first_frame = req.get("first_frame")
        last_frame = req.get("last_frame")
        path = "/image_to_video" if first_frame else "/text_to_video"
        body = {
            "model": model,
            "promptText": req["prompt"],
            "ratio": RATIOS.get(req.get("aspect_ratio"), req.get("aspect_ratio")),
            "duration": int(req["seconds"]),
        }
        if first_frame and last_frame:
            body["promptImage"] = [
                {"uri": data_url(first_frame), "position": "first"},
                {"uri": data_url(last_frame), "position": "last"},
            ]
        elif first_frame:
            body["promptImage"] = data_url(first_frame)
        out = self.transport("POST", self.base_url + path, headers=self._headers(), body=body)
        return {"job_id": out["id"], "model": model}

    def video_poll(self, job):
        body = self._get("/tasks/" + job["job_id"])
        status = body.get("status")
        if status in ("PENDING", "RUNNING", "THROTTLED"):
            return {"status": "pending", "error": None, "cost": None}
        if status == "SUCCEEDED":
            return {"status": "done", "error": None, "cost": None}
        return {"status": "failed", "error": body.get("failure") or "generation failed", "cost": None}

    def video_download(self, job):
        body = self._get("/tasks/" + job["job_id"])
        out = body.get("output") or []
        if body.get("status") != "SUCCEEDED" or not out:
            raise Retryable("not finished")
        return self.transport("GET", out[0], raw=True)
