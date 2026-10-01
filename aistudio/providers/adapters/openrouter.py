"""OpenRouter: one key, many models.  chat/vision/image/video, and it REPORTS the dollar cost (usage.cost).  Standard library only.

OpenAI-compatible chat plus OpenRouter's own /images and /videos endpoints (same request shapes the app has used since v1).
"""
import base64

from aistudio.providers.adapters.openai import OpenAIAdapter
from aistudio.providers.base import Rejected, Retryable, data_url


class OpenRouterAdapter(OpenAIAdapter):
    type = "openrouter"
    capabilities = frozenset({"chat", "vision", "image", "video"})
    default_base_url = "https://openrouter.ai/api/v1"

    def _headers(self):
        k = self.secret.get("api_key")
        return {"Authorization": f"Bearer {k}"} if k else {}

    def _call(self, method, path, body=None, raw=False):
        return self.transport(method, self.base_url + path, headers=self._headers(), body=body, raw=raw)

    def list_models(self):
        out = []
        for m in (self._call("GET", "/models").get("data") or []):
            mid = m.get("id", "")
            outs = ((m.get("architecture") or {}).get("output_modalities")) or ["text"]
            out.append({"id": mid, "name": m.get("name") or mid, "capability": "image" if "image" in outs and "text" not in outs else "chat",
                        "free": str((m.get("pricing") or {}).get("prompt", "1")) in ("0", "0.0") and str((m.get("pricing") or {}).get("completion", "1")) in ("0", "0.0")})
        return out

    def test(self):
        try:
            d = self._call("GET", "/key").get("data", {})
            lim, left = d.get("limit"), d.get("limit_remaining")
            extra = f" · ${left:.2f} left of ${lim:.0f}" if lim is not None and left is not None else (f" · ${d.get('usage', 0):.2f} used" if d.get("usage") is not None else "")
            return {"ok": True, "message": "Connected successfully" + extra}
        except Exception as e:
            from aistudio.providers.base import scrub
            return {"ok": False, "message": scrub(e, self.secret)[:200]}

    def _complete(self, model, messages, opts):
        opts = opts or {}
        body = {"model": model, "messages": messages, "max_tokens": opts.get("max_tokens", 3500), "temperature": opts.get("temperature", 0.4), "usage": {"include": True}}
        r = self._call("POST", "/chat/completions", body)
        text = ((r.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
        if not text.strip():
            raise Retryable("empty answer")
        u = r.get("usage") or {}
        return {"text": text, "usage": {"input": u.get("prompt_tokens", 0), "output": u.get("completion_tokens", 0)},
                "cost": float(u["cost"]) if isinstance(u.get("cost"), (int, float)) else None, "model": model}

    def chat(self, model, messages, opts=None):
        return self._complete(model, messages, opts)

    def vision(self, model, prompt, images, opts=None):
        content = [{"type": "text", "text": prompt}] + [{"type": "image_url", "image_url": {"url": data_url(p)}} for p in images]
        return self._complete(model, [{"role": "user", "content": content}], opts)

    def image(self, model, prompt, refs=(), aspect_ratio="9:16", opts=None):
        if len(refs) > 4:
            raise Rejected("at most 4 reference images")
        body = {"model": model, "prompt": prompt, "aspect_ratio": aspect_ratio, "resolution": (opts or {}).get("resolution", "2K"), "n": 1,
                "input_references": [{"type": "image_url", "image_url": {"url": data_url(r)}} for r in refs]}
        r = self._call("POST", "/images", body)
        items = r.get("data") or []
        if not items or not items[0].get("b64_json"):
            raise Retryable("no image in response")
        c = (r.get("usage") or {}).get("cost")
        return {"bytes": base64.b64decode(items[0]["b64_json"]), "usage": {}, "cost": float(c) if isinstance(c, (int, float)) else None, "model": model}

    def video_submit(self, model, req):
        body = {"model": model, "prompt": req["prompt"], "duration": req["seconds"], "resolution": req.get("resolution", "720p"),
                "aspect_ratio": req.get("aspect_ratio", "9:16"), "generate_audio": bool(req.get("audio"))}
        if req.get("first_frame"):
            body["frame_images"] = [{"type": "image_url", "image_url": {"url": data_url(req["first_frame"])}, "frame_type": "first_frame"}]
        return {"job_id": self._call("POST", "/videos", body)["id"], "model": model}

    def video_poll(self, job):
        r = self._call("GET", f"/videos/{job['job_id']}")
        st = r.get("status")
        c = (r.get("usage") or {}).get("cost")
        cost = float(c) if isinstance(c, (int, float)) else None
        if st == "completed":
            return {"status": "done", "error": None, "cost": cost}
        if st == "failed":
            return {"status": "failed", "error": str(r.get("error") or "generation failed"), "cost": cost}
        return {"status": "pending", "error": None, "cost": None}

    def video_download(self, job):
        return self._call("GET", f"/videos/{job['job_id']}/content?index=0", raw=True)
