"""Kling AI video.  Standard library only.

NOTE: shapes are from Kling's public API and must be re-checked against the live docs before release.
Subclass of aistudio.providers.base.Adapter (read its docstring first).
  type = "kling" ; capabilities = {"video"} ; default_base_url = "https://api.klingai.com"
  Secret has TWO fields: self.secret["access_key"] and self.secret["secret_key"].
  Auth header on every request: {"Authorization": "Bearer " + token} where token is a JWT (HS256) made with the standard library:
    header {"alg":"HS256","typ":"JWT"}, payload {"iss": access_key, "exp": int(now)+1800, "nbf": int(now)-5}, signature = HMAC-SHA256(secret_key)
    over "b64url(header).b64url(payload)"; all three parts base64url WITHOUT padding. `now` = self.clock() (default time.time; the constructor
    accepts an optional `clock` keyword so tests can fix the time: __init__(self, conn, transport=None, clock=time.time)).
  Provide a method make_token() -> str that returns the JWT.

list_models(): fixed list: [{"id":"kling-v1-6","name":"Kling 1.6","capability":"video"},{"id":"kling-v2-master","name":"Kling 2 Master","capability":"video"}].
test(): GET /v1/videos/text2video?pageNum=1&pageSize=1 ; ok True "Connected successfully" when the response has "code" == 0, else
  {"ok": False, "message": (body.get("message") or "rejected")[:200]}; provider errors -> {"ok": False, "message": scrub(e, self.secret)[:200]}. Never raises.

video_submit(model, req): kind = "image2video" if req.get("first_frame") else "text2video". POST /v1/videos/{kind} body
  {"model_name": model, "prompt": req["prompt"], "duration": "5" if seconds <= 5 else "10" (string), "aspect_ratio": req["aspect_ratio"], "mode": "std"}
  plus, for image2video, "image": b64_of(path) (plain base64, no data: prefix). Response {"code":0,"data":{"task_id":...}} ->
  {"job_id": f"{kind}:{task_id}", "model": model}. If code != 0 raise Rejected(body.get("message") or "rejected") (Rejected is in base).
video_poll(job): kind, task_id = job["job_id"].split(":",1); GET /v1/videos/{kind}/{task_id}; data.task_status: "submitted"/"processing" =>
  pending; "succeed" => done; "failed" => {"status":"failed","error": data.get("task_status_msg") or "generation failed","cost":None}.
  Return the same dict keys as the other adapters: {"status","error","cost":None}.
video_download(job): GET the same status URL; if task_status != "succeed" raise Retryable("not finished"); url = data["task_result"]["videos"][0]["url"];
  return self.transport("GET", url, raw=True) (no auth header).
"""
import base64
import hashlib
import hmac
import json
import time

from aistudio.providers.base import Adapter, Rejected, Retryable, b64_of, scrub


class KlingAdapter(Adapter):
    type = "kling"
    capabilities = frozenset({"video"})
    default_base_url = "https://api.klingai.com"

    def __init__(self, conn, transport=None, clock=time.time):
        super().__init__(conn, transport)
        self.clock = clock

    def _b64url_encode(self, data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode()

    def _b64url_decode(self, s: str) -> bytes:
        padding = "=" * (-len(s) % 4)
        return base64.urlsafe_b64decode(s + padding)

    def make_token(self) -> str:
        now = int(self.clock())
        header = {"alg": "HS256", "typ": "JWT"}
        payload = {"iss": self.secret["access_key"], "exp": now + 1800, "nbf": now - 5}
        header_b64 = self._b64url_encode(json.dumps(header, separators=(",", ":")).encode())
        payload_b64 = self._b64url_encode(json.dumps(payload, separators=(",", ":")).encode())
        signing_input = f"{header_b64}.{payload_b64}".encode()
        signature = hmac.new(
            self.secret["secret_key"].encode(),
            signing_input,
            hashlib.sha256
        ).digest()
        sig_b64 = self._b64url_encode(signature)
        return f"{header_b64}.{payload_b64}.{sig_b64}"

    def list_models(self):
        return [
            {"id": "kling-v1-6", "name": "Kling 1.6", "capability": "video"},
            {"id": "kling-v2-master", "name": "Kling 2 Master", "capability": "video"},
        ]

    def test(self):
        try:
            token = self.make_token()
            resp = self.transport(
                "GET",
                f"{self.base_url}/v1/videos/text2video?pageNum=1&pageSize=1",
                headers={"Authorization": f"Bearer {token}"}
            )
            body = resp if isinstance(resp, dict) else json.loads(resp)
            if body.get("code") == 0:
                return {"ok": True, "message": "Connected successfully"}
            return {"ok": False, "message": (body.get("message") or "rejected")[:200]}
        except Exception as e:
            return {"ok": False, "message": scrub(e, self.secret)[:200]}

    def video_submit(self, model, req):
        token = self.make_token()
        kind = "image2video" if req.get("first_frame") else "text2video"
        seconds = req.get("seconds", 5)
        duration = "5" if seconds <= 5 else "10"
        body = {
            "model_name": model,
            "prompt": req["prompt"],
            "duration": duration,
            "aspect_ratio": req["aspect_ratio"],
            "mode": "std"
        }
        if kind == "image2video":
            body["image"] = b64_of(req["first_frame"])

        resp = self.transport(
            "POST",
            f"{self.base_url}/v1/videos/{kind}",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            body=body
        )
        data = resp if isinstance(resp, dict) else json.loads(resp)
        if data.get("code") != 0:
            raise Rejected(data.get("message") or "rejected")
        task_id = data["data"]["task_id"]
        return {"job_id": f"{kind}:{task_id}", "model": model}

    def video_poll(self, job):
        token = self.make_token()
        kind, task_id = job["job_id"].split(":", 1)
        resp = self.transport(
            "GET",
            f"{self.base_url}/v1/videos/{kind}/{task_id}",
            headers={"Authorization": f"Bearer {token}"}
        )
        data = (resp if isinstance(resp, dict) else json.loads(resp)).get("data", {})
        status = data.get("task_status")
        if status in ("submitted", "processing"):
            return {"status": "pending", "error": None, "cost": None}
        if status == "succeed":
            return {"status": "done", "error": None, "cost": None}
        if status == "failed":
            return {"status": "failed", "error": data.get("task_status_msg") or "generation failed", "cost": None}
        return {"status": "pending", "error": None, "cost": None}

    def video_download(self, job):
        token = self.make_token()
        kind, task_id = job["job_id"].split(":", 1)
        resp = self.transport(
            "GET",
            f"{self.base_url}/v1/videos/{kind}/{task_id}",
            headers={"Authorization": f"Bearer {token}"}
        )
        data = (resp if isinstance(resp, dict) else json.loads(resp)).get("data", {})
        if data.get("task_status") != "succeed":
            raise Retryable("not finished")
        url = data["task_result"]["videos"][0]["url"]
        return self.transport("GET", url, raw=True)