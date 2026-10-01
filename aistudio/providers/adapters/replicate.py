"""Replicate (image and video models via predictions).  Standard library only.

NOTE: shapes are from Replicate's public API and must be re-checked against the live docs before release.
Subclass of aistudio.providers.base.Adapter (read its docstring first).
  type = "replicate" ; capabilities = {"image","video"} ; default_base_url = "https://api.replicate.com/v1"
  Header on EVERY request: {"Authorization": "Bearer " + api_key}.   Models are "owner/name" strings.

list_models(): fixed list of examples the user can extend elsewhere:
  [{"id":"black-forest-labs/flux-1.1-pro","name":"FLUX 1.1 Pro","capability":"image"},
   {"id":"minimax/video-01","name":"MiniMax Video 01","capability":"video"}].
test(): GET /account ; ok True "Connected successfully" else {"ok": False, "message": scrub(error, self.secret)[:200]}. Never raises.

Submitting: POST /models/{model}/predictions body {"input": INPUT} -> response {"id": ...}.  INPUT for video: {"prompt": req["prompt"],
  "duration": int(seconds), "aspect_ratio": req["aspect_ratio"]} plus "first_frame_image": data_url(path) when first_frame is given;
  INPUT for image: {"prompt": prompt, "aspect_ratio": aspect_ratio} plus "image": data_url(refs[0]) when refs is non-empty.
  In both cases, if opts/req has "input_extra" (a dict) merge it over INPUT.
video_submit(model, req) -> {"job_id": id, "model": model}.
video_poll(job): GET /predictions/{job_id}; status "starting"/"processing" => pending; "succeeded" => done; "failed"/"canceled" =>
  {"status":"failed","error": body.get("error") or "generation failed","cost":None}. Result dicts: {"status","error","cost":None}.
video_download(job): GET /predictions/{job_id}; if status != "succeeded" raise Retryable("not finished"); output is a URL string or a list
  (take the first element); return self.transport("GET", url, raw=True) without auth headers.
image(model, prompt, refs=(), aspect_ratio="9:16", opts=None): submit as above, then poll GET /predictions/{id} up to opts.get("max_polls", 60)
  times calling self.sleep(opts.get("poll_seconds", 2)) between polls (self.sleep is set in __init__(conn, transport=None, sleep=time.sleep)).
  succeeded -> download the output URL (raw) -> {"bytes","usage":{},"cost":None,"model"}; failed -> raise Rejected(error); never finishing -> raise Retryable("timed out").
"""
import time

from aistudio.providers.base import Adapter, Rejected, Retryable, data_url, scrub


class ReplicateAdapter(Adapter):
    type = "replicate"
    capabilities = frozenset({"image", "video"})
    default_base_url = "https://api.replicate.com/v1"

    def __init__(self, conn, transport=None, sleep=time.sleep):
        super().__init__(conn, transport)
        self.sleep = sleep

    @property
    def _headers(self):
        return {"Authorization": "Bearer " + (self.secret.get("api_key") or "")}

    def _get(self, path):
        return self.transport("GET", self.base_url + path, headers=self._headers)

    def _submit(self, model, inputs):
        body = self.transport("POST", self.base_url + "/models/" + model + "/predictions",
                              headers=self._headers, body={"input": inputs})
        return body.get("id")

    @staticmethod
    def _output_url(body):
        out = body.get("output")
        if isinstance(out, list):
            out = out[0] if out else None
        return out

    def list_models(self):
        return [
            {"id": "black-forest-labs/flux-1.1-pro", "name": "FLUX 1.1 Pro", "capability": "image"},
            {"id": "minimax/video-01", "name": "MiniMax Video 01", "capability": "video"},
        ]

    def test(self):
        try:
            self._get("/account")
        except Exception as e:
            return {"ok": False, "message": scrub(e, self.secret)[:200]}
        return {"ok": True, "message": "Connected successfully"}

    def image(self, model, prompt, refs=(), aspect_ratio="9:16", opts=None):
        opts = opts or {}
        inputs = {"prompt": prompt, "aspect_ratio": aspect_ratio}
        if refs:
            inputs["image"] = data_url(refs[0])
        extra = opts.get("input_extra")
        if isinstance(extra, dict):
            inputs.update(extra)
        path = "/predictions/" + str(self._submit(model, inputs))
        for i in range(int(opts.get("max_polls", 60))):
            if i:
                self.sleep(opts.get("poll_seconds", 2))
            body = self._get(path)
            status = body.get("status")
            if status == "succeeded":
                url = self._output_url(body)
                if not url:
                    raise Retryable("no image in response")
                return {"bytes": self.transport("GET", url, headers={}, raw=True),
                        "usage": {}, "cost": None, "model": model}
            if status in ("failed", "canceled"):
                raise Rejected(body.get("error") or "generation failed")
        raise Retryable("timed out")

    def video_submit(self, model, req):
        inputs = {"prompt": req["prompt"], "duration": int(req["seconds"]),
                  "aspect_ratio": req["aspect_ratio"]}
        if req.get("first_frame"):
            inputs["first_frame_image"] = data_url(req["first_frame"])
        extra = req.get("input_extra")
        if isinstance(extra, dict):
            inputs.update(extra)
        return {"job_id": self._submit(model, inputs), "model": model}

    def video_poll(self, job):
        body = self._get("/predictions/" + job["job_id"])
        status = body.get("status")
        if status == "succeeded":
            return {"status": "done", "error": None, "cost": None}
        if status in ("failed", "canceled"):
            return {"status": "failed", "error": body.get("error") or "generation failed", "cost": None}
        return {"status": "pending", "error": None, "cost": None}

    def video_download(self, job):
        body = self._get("/predictions/" + job["job_id"])
        if body.get("status") != "succeeded":
            raise Retryable("not finished")
        url = self._output_url(body)
        if not url:
            raise Retryable("not finished")
        return self.transport("GET", url, headers={}, raw=True)
