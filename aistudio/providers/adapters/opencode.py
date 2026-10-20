"""OpenCode Console inference API adapter (https://opencode.ai/v2/docs/console/inference/). Standard library only.

Endpoints served:
- OpenAI Chat Completions: /openai/v1/chat/completions (open models: kimi, glm, minimax, mimo, qwen, deepseek)
- OpenAI Responses: /openai/v1/responses (gpt models)
- Anthropic Messages: /anthropic/v1/messages (claude models)
- Gemini Generate Content: /google/v1beta/models/<model>:generateContent (gemini models)
- Models Listing: /v1/models
"""
from aistudio.providers.base import Adapter, Retryable, Unsupported, b64_of, data_url, mime_of


class OpenCodeAdapter(Adapter):
    type = "opencode"
    capabilities = frozenset({"chat", "vision"})
    default_base_url = "https://opencode.ai/inference"

    def _headers(self):
        k = (self.secret or {}).get("api_key")
        h = {
            "Content-Type": "application/json",
            "User-Agent": "AIStudio/1.0 (Macintosh; OpenCode-Client)",
        }
        if k:
            h["Authorization"] = f"Bearer {k}"
        return h

    def _base(self):
        return (self.base_url or self.default_base_url).rstrip("/")

    def list_models(self):
        data = self.transport("GET", f"{self._base()}/v1/models", headers=self._headers())
        out = []
        for m in (data.get("data") if isinstance(data, dict) else []) or []:
            mid = m.get("id", "")
            out.append({
                "id": mid,
                "name": m.get("name") or mid,
                "capability": "chat",
                "free": "free" in mid.lower(),
            })
        out.sort(key=lambda m: m["id"])
        return out

    def test(self):
        try:
            models = self.list_models()
            return {"ok": True, "message": f"Connected successfully ({len(models)} models available)"}
        except Exception as e:
            from aistudio.providers.base import scrub
            return {"ok": False, "message": scrub(e, self.secret)[:200]}

    def _complete_anthropic(self, model, messages, opts):
        opts = opts or {}
        system = "\n\n".join(m.get("content") or "" for m in messages if m.get("role") == "system")
        user_msgs = [m for m in messages if m.get("role") != "system"]
        if not user_msgs:
            user_msgs = [{"role": "user", "content": "Hello"}]
        body = {
            "model": model,
            "max_tokens": opts.get("max_tokens", 3500),
            "messages": user_msgs,
        }
        if system:
            body["system"] = system
        if "temperature" in opts:
            body["temperature"] = opts["temperature"]
        resp = self.transport("POST", f"{self._base()}/anthropic/v1/messages", headers=self._headers(), body=body)
        text = "".join(b.get("text", "") for b in (resp.get("content") or []) if b.get("type") == "text")
        if not text.strip():
            raise Retryable("empty answer")
        u = resp.get("usage") or {}
        return {
            "text": text,
            "usage": {"input": u.get("input_tokens") or 0, "output": u.get("output_tokens") or 0},
            "cost": None,
            "model": model,
        }

    def _complete_gemini(self, model, messages, opts):
        opts = opts or {}
        contents = []
        system = "\n\n".join(m.get("content") or "" for m in messages if m.get("role") == "system")
        for m in messages:
            if m.get("role") == "system":
                continue
            role = "user" if m.get("role") in ("user",) else "model"
            c = m.get("content")
            if isinstance(c, list):
                parts = []
                for p in c:
                    if p.get("type") == "text":
                        parts.append({"text": p.get("text", "")})
                    elif p.get("type") == "inlineData":
                        parts.append({"inlineData": p.get("inlineData", {})})
                contents.append({"role": role, "parts": parts})
            else:
                contents.append({"role": role, "parts": [{"text": str(c or "")}]})
        body = {"contents": contents}
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}
        gen_cfg = {}
        if "max_tokens" in opts:
            gen_cfg["maxOutputTokens"] = opts["max_tokens"]
        if "temperature" in opts:
            gen_cfg["temperature"] = opts["temperature"]
        if gen_cfg:
            body["generationConfig"] = gen_cfg
        resp = self.transport(
            "POST",
            f"{self._base()}/google/v1beta/models/{model}:generateContent",
            headers=self._headers(),
            body=body,
        )
        parts = (((resp.get("candidates") or [{}])[0] or {}).get("content") or {}).get("parts") or []
        text = "".join(p.get("text", "") for p in parts)
        if not text.strip():
            raise Retryable("empty answer")
        um = resp.get("usageMetadata") or {}
        return {
            "text": text,
            "usage": {"input": um.get("promptTokenCount") or 0, "output": um.get("candidatesTokenCount") or 0},
            "cost": None,
            "model": model,
        }

    def _complete_responses(self, model, messages, opts):
        opts = opts or {}
        prompt_text = "\n\n".join(f"{m.get('role', 'user')}: {m.get('content', '')}" for m in messages)
        body = {"model": model, "input": prompt_text}
        resp = self.transport("POST", f"{self._base()}/openai/v1/responses", headers=self._headers(), body=body)
        text = ""
        if "output_text" in resp:
            text = resp["output_text"]
        elif "output" in resp and isinstance(resp["output"], list):
            for item in resp["output"]:
                if item.get("type") == "message":
                    for part in (item.get("content") or []):
                        if part.get("type") == "text":
                            text += part.get("text", "")
        elif "choices" in resp:
            text = (resp.get("choices") or [{}])[0].get("message", {}).get("content") or ""
        if not text.strip():
            raise Retryable("empty answer")
        u = resp.get("usage") or {}
        usage = {
            "input": u.get("input_tokens") or u.get("prompt_tokens") or 0,
            "output": u.get("output_tokens") or u.get("completion_tokens") or 0,
        }
        return {"text": text, "usage": usage, "cost": None, "model": model}

    def _complete_openai(self, model, messages, opts):
        opts = opts or {}
        body = {"model": model, "messages": messages}
        for k in ("max_tokens", "temperature"):
            if k in opts:
                body[k] = opts[k]
        resp = self.transport("POST", f"{self._base()}/openai/v1/chat/completions", headers=self._headers(), body=body)
        msg = (resp.get("choices") or [{}])[0].get("message") or {}
        text = msg.get("content") or ""
        if not text.strip():
            raise Retryable("empty answer")
        u = resp.get("usage") or {}
        usage = {"input": u.get("prompt_tokens", 0) or 0, "output": u.get("completion_tokens", 0) or 0}
        cost = u.get("cost")
        return {"text": text, "usage": usage, "cost": cost if isinstance(cost, (int, float)) else None, "model": model}

    def chat(self, model, messages, opts=None):
        m = model.lower()
        if m.startswith("claude-"):
            return self._complete_anthropic(model, messages, opts)
        if m.startswith("gemini-"):
            return self._complete_gemini(model, messages, opts)
        if m.startswith("gpt-"):
            return self._complete_responses(model, messages, opts)
        return self._complete_openai(model, messages, opts)

    def vision(self, model, prompt, images, opts=None):
        m = model.lower()
        if m.startswith("claude-"):
            content = [
                {"type": "image", "source": {"type": "base64", "media_type": mime_of(p), "data": b64_of(p)}}
                for p in images
            ]
            content.append({"type": "text", "text": prompt})
            return self._complete_anthropic(model, [{"role": "user", "content": content}], opts)
        if m.startswith("gemini-"):
            parts = [{"text": prompt}]
            for p in images:
                parts.append({"inlineData": {"mimeType": mime_of(p), "data": b64_of(p)}})
            return self._complete_gemini(model, [{"role": "user", "content": parts}], opts)

        content = [{"type": "text", "text": prompt}]
        content += [{"type": "image_url", "image_url": {"url": data_url(p)}} for p in images]
        return self._complete_openai(model, [{"role": "user", "content": content}], opts)

    def image(self, model, prompt, refs=(), aspect_ratio="9:16", opts=None):
        raise Unsupported("OpenCode Console inference does not currently support image generation")
