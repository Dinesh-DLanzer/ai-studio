"""Anthropic Claude (Messages API).  Standard library only.

Subclass of aistudio.providers.base.Adapter (read its docstring first: transport, errors, result shapes).
  type = "anthropic" ; capabilities = {"chat","vision"} ; default_base_url = "https://api.anthropic.com/v1"
  Headers on EVERY request: {"x-api-key": self.secret["api_key"], "anthropic-version": "2023-06-01"}.  URLs are base_url + path.

list_models(): GET /models -> {"data":[{"id","display_name"}]}. Return [{"id","name": display_name or id,"capability":"chat"}] in the order given.

chat(model, messages, opts=None): POST /messages with body {"model": model, "max_tokens": opts.get("max_tokens", 3500), "messages": M}
  plus "temperature" when in opts. messages use OpenAI style [{"role","content"(str)}]: every message with role "system" is removed from M and
  their contents joined with "\n\n" go into body["system"] (omit "system" when there are none). Other messages are passed through unchanged.
  Response: content = list of blocks; text = "".join(b["text"] for blocks with type "text"). usage.input_tokens/output_tokens -> usage
  {"input","output"} (0 if absent). cost = None. Blank text -> raise Retryable("empty answer"). Returns {"text","usage","cost":None,"model"}.

vision(model, prompt, images, opts=None): same endpoint; one user message whose content is a list: first one image block per path
  {"type":"image","source":{"type":"base64","media_type": mime_of(path),"data": b64_of(path)}} then {"type":"text","text": prompt}
  (mime_of / b64_of come from aistudio.providers.base).

image / video_*: inherited (Unsupported).
"""
from aistudio.providers.base import Adapter, Retryable, b64_of, mime_of


class AnthropicAdapter(Adapter):
    type = "anthropic"
    capabilities = frozenset({"chat", "vision"})
    default_base_url = "https://api.anthropic.com/v1"

    def _headers(self):
        return {"x-api-key": self.secret["api_key"], "anthropic-version": "2023-06-01"}

    def list_models(self):
        data = self.transport("GET", self.base_url + "/models", headers=self._headers())
        return [{"id": m["id"], "name": m.get("display_name") or m["id"], "capability": "chat"}
                for m in data.get("data") or []]

    def _complete(self, model, messages, opts):
        opts = opts or {}
        system = "\n\n".join(m.get("content") or "" for m in messages if m.get("role") == "system")
        body = {"model": model, "max_tokens": opts.get("max_tokens", 3500),
                "messages": [m for m in messages if m.get("role") != "system"]}
        if "temperature" in opts:
            body["temperature"] = opts["temperature"]
        if system:
            body["system"] = system
        data = self.transport("POST", self.base_url + "/messages", headers=self._headers(), body=body)
        text = "".join(b.get("text", "") for b in data.get("content") or [] if b.get("type") == "text")
        if not text.strip():
            raise Retryable("empty answer")
        u = data.get("usage") or {}
        return {"text": text,
                "usage": {"input": u.get("input_tokens") or 0, "output": u.get("output_tokens") or 0},
                "cost": None, "model": model}

    def chat(self, model, messages, opts=None):
        return self._complete(model, messages, opts)

    def vision(self, model, prompt, images, opts=None):
        content = [{"type": "image", "source": {"type": "base64", "media_type": mime_of(p), "data": b64_of(p)}}
                   for p in images]
        content.append({"type": "text", "text": prompt})
        return self._complete(model, [{"role": "user", "content": content}], opts)
