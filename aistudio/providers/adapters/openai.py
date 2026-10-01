"""OpenAI and OpenAI-compatible APIs (OpenAI, Groq, Together, LM Studio, Ollama, any gateway with /chat/completions).  Standard library only.

Subclass of aistudio.providers.base.Adapter (read its docstring first: transport, errors, result shapes).
  type = "openai" ; capabilities = {"chat","vision","image"} ; default_base_url = "https://api.openai.com/v1"
  Auth header on EVERY request: {"Authorization": "Bearer " + self.secret["api_key"]}  (omit the header when api_key is missing/empty,
  local servers need none).
  URLs are base_url + path.

list_models(): GET /models -> {"data":[{"id":...}]}. Return [{"id": id, "name": id, "capability": "image" if the id starts with
  "dall-e" or "gpt-image" else "chat"}] sorted by id.

chat(model, messages, opts=None): POST /chat/completions with body {"model": model, "messages": messages} plus "max_tokens" and
  "temperature" ONLY when present in opts. Response: choices[0].message.content (str) -> text; usage.prompt_tokens/completion_tokens ->
  usage {"input","output"} (0 if absent). cost = usage["cost"] if that is a number else None. Empty/blank text -> raise Retryable("empty answer").
  Returns {"text","usage","cost","model"}.

vision(model, prompt, images, opts=None): same endpoint; messages = [{"role":"user","content":[{"type":"text","text":prompt}] +
  [{"type":"image_url","image_url":{"url": data_url(path)}} for each path]}] (data_url from aistudio.providers.base).

image(model, prompt, refs=(), aspect_ratio="9:16", opts=None): if refs is non-empty raise Unsupported("reference images ...").
  POST /images/generations body {"model","prompt","n":1,"size": S} where S = "1024x1536" if the aspect ratio's width < height,
  "1536x1024" if width > height, else "1024x1024" (aspect_ratio is "W:H"). If model starts with "dall-e" also add "response_format":"b64_json".
  Response data[0].b64_json (base64) -> bytes; else if data[0].url -> self.transport("GET", url, raw=True). Neither -> Retryable("no image in response").
  Returns {"bytes","usage":{},"cost":None,"model"}.

video_*: inherited (Unsupported).
"""
import base64

from aistudio.providers.base import Adapter, Retryable, Unsupported, data_url


class OpenAIAdapter(Adapter):
    type = "openai"
    capabilities = frozenset({"chat", "vision", "image"})
    default_base_url = "https://api.openai.com/v1"

    def _headers(self):
        key = self.secret.get("api_key")
        return {"Authorization": "Bearer " + key} if key else {}

    def _post(self, path, body):
        return self.transport("POST", self.base_url + path, headers=self._headers(), body=body)

    def list_models(self):
        data = self.transport("GET", self.base_url + "/models", headers=self._headers())
        out = []
        for m in data.get("data", []):
            mid = m.get("id", "")
            cap = "image" if mid.startswith(("dall-e", "gpt-image")) else "chat"
            out.append({"id": mid, "name": mid, "capability": cap})
        out.sort(key=lambda m: m["id"])
        return out

    def chat(self, model, messages, opts=None):
        body = {"model": model, "messages": messages}
        for k in ("max_tokens", "temperature"):
            if opts and k in opts:
                body[k] = opts[k]
        resp = self._post("/chat/completions", body)
        msg = (resp.get("choices") or [{}])[0].get("message") or {}
        text = msg.get("content") or ""
        if not text.strip():
            raise Retryable("empty answer")
        u = resp.get("usage") or {}
        usage = {"input": u.get("prompt_tokens", 0) or 0, "output": u.get("completion_tokens", 0) or 0}
        cost = u.get("cost")
        return {"text": text, "usage": usage, "cost": cost if isinstance(cost, (int, float)) else None, "model": model}

    def vision(self, model, prompt, images, opts=None):
        content = [{"type": "text", "text": prompt}]
        content += [{"type": "image_url", "image_url": {"url": data_url(p)}} for p in images]
        return self.chat(model, [{"role": "user", "content": content}], opts)

    def image(self, model, prompt, refs=(), aspect_ratio="9:16", opts=None):
        if refs:
            raise Unsupported("reference images are not supported by openai image()")
        w, h = (int(x) for x in aspect_ratio.split(":", 1))
        size = "1024x1536" if w < h else "1536x1024" if w > h else "1024x1024"
        body = {"model": model, "prompt": prompt, "n": 1, "size": size}
        if model.startswith("dall-e"):
            body["response_format"] = "b64_json"
        resp = self._post("/images/generations", body)
        d = (resp.get("data") or [{}])[0]
        if d.get("b64_json"):
            return {"bytes": base64.b64decode(d["b64_json"]), "usage": {}, "cost": None, "model": model}
        if d.get("url"):
            return {"bytes": self.transport("GET", d["url"], raw=True), "usage": {}, "cost": None, "model": model}
        raise Retryable("no image in response")
