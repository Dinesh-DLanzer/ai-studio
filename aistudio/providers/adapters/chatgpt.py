"""ChatGPT Plus/Pro subscription through OAuth (the backend the Codex CLI uses).  Standard library only.

Subclass of aistudio.providers.base.Adapter.  type = "chatgpt" ; capabilities = {"chat","vision","image"} ;
default_base_url = "https://chatgpt.com/backend-api".  No API key: the secret is an OAuth session
{"access_token","refresh_token","account_id","expires_at"} (see aistudio.providers.chatgpt_auth).  An expired access token is refreshed
before the call; conn["on_secret"](new_secret), when given, persists it.

Every call is POST {base}/codex/responses (Responses API, server-sent events, always streamed, store=false).  The transport is asked for the
raw bytes and the event stream is parsed here:
  response.output_text.delta {delta}                         -> text
  response.completed {response:{usage:{input_tokens,output_tokens}}} -> usage
  response.output_item.done {item:{type:"image_generation_call","result":<base64>}} -> image bytes
`system` messages become `instructions`.  cost is 0.0 (the subscription is flat-rate), never None.
Video is not offered by ChatGPT: video_* inherited (Unsupported).
"""
import base64
import json
from pathlib import Path

from aistudio.providers import chatgpt_auth
from aistudio.providers.base import Adapter, ProviderError, Retryable, Unsupported, data_url

# Model names a ChatGPT account may use change over time and differ per account, so they are read from the local Codex install
# (models_cache.json "list"-visible models, plus the `model =` in config.toml) and only fall back to this list when Codex is absent.
FALLBACK_MODELS = ["gpt-5.6-luna", "gpt-5.6-terra", "gpt-5.5"]
IMAGE_MODEL = "gpt-image-1"


def chat_models(codex_dir=None):
    d = Path(codex_dir) if codex_dir else chatgpt_auth.codex_auth_path().parent
    out = []
    try:
        for m in sorted(json.loads((d / "models_cache.json").read_text(encoding="utf-8")).get("models", []), key=lambda m: m.get("priority", 99)):
            if m.get("visibility") == "list" and m.get("slug"):
                out.append(m["slug"])
    except (OSError, ValueError, AttributeError):
        pass
    try:
        for line in (d / "config.toml").read_text(encoding="utf-8").splitlines():
            if line.startswith("model") and line.split("=")[0].strip() == "model":
                cur = line.split("=", 1)[1].strip().strip("\"'")
                if cur and cur not in out:
                    out.insert(0, cur)
                break
    except OSError:
        pass
    return out or list(FALLBACK_MODELS)


DEFAULT_INSTRUCTIONS = "You are a helpful assistant."


class ChatGPTAdapter(Adapter):
    type = "chatgpt"
    capabilities = frozenset({"chat", "vision", "image"})
    default_base_url = "https://chatgpt.com/backend-api"

    # ---- auth
    def _get_valid_token(self):
        def save(fresh):
            self.secret = fresh
            cb = self.conn.get("on_secret")
            if cb:
                cb(fresh)
        self.secret = chatgpt_auth.valid_secret(self.transport, self.secret, on_update=save)
        return self.secret["access_token"]

    def _headers(self):
        h = {"Authorization": "Bearer " + self._get_valid_token(), "OpenAI-Beta": "responses=experimental",
             "originator": "codex_cli_rs", "Accept": "text/event-stream"}
        if self.secret.get("account_id"):
            h["chatgpt-account-id"] = self.secret["account_id"]
        return h

    # ---- protocol
    @staticmethod
    def _input(messages):
        instructions, items = [], []
        for m in messages:
            role, content = m.get("role", "user"), m.get("content", "")
            if role == "system":
                instructions.append(content if isinstance(content, str) else "")
                continue
            kind = "output_text" if role == "assistant" else "input_text"
            if isinstance(content, str):
                parts = [{"type": kind, "text": content}]
            else:
                parts = []
                for c in content:
                    if c.get("type") == "text":
                        parts.append({"type": kind, "text": c.get("text", "")})
                    elif c.get("type") == "image_url":
                        parts.append({"type": "input_image", "image_url": (c.get("image_url") or {}).get("url", "")})
            items.append({"type": "message", "role": role, "content": parts})
        return "\n\n".join(i for i in instructions if i) or DEFAULT_INSTRUCTIONS, items

    def _run(self, body):
        """POST one request and fold the SSE stream into {"text","usage","images"}."""
        raw = self.transport("POST", self.base_url + "/codex/responses", headers=self._headers(),
                             body={**body, "stream": True, "store": False}, raw=True)
        if isinstance(raw, dict):               # a transport that already parsed it (tests, gateways)
            raw = json.dumps(raw).encode()
        text, usage, images, final = [], {"input": 0, "output": 0}, [], None
        for line in raw.decode("utf-8", "replace").splitlines():
            if not line.startswith("data:"):
                continue
            try:
                ev = json.loads(line[5:].strip())
            except ValueError:
                continue
            t = ev.get("type", "")
            if t == "response.output_text.delta":
                text.append(ev.get("delta", ""))
            elif t == "response.output_item.done":
                item = ev.get("item") or {}
                if item.get("type") == "image_generation_call" and item.get("result"):
                    images.append(item["result"])
            elif t in ("response.completed", "response.done"):
                final = ev.get("response") or {}
                u = final.get("usage") or {}
                usage = {"input": u.get("input_tokens", 0) or 0, "output": u.get("output_tokens", 0) or 0}
            elif t in ("response.failed", "error"):
                err = (ev.get("response") or {}).get("error") or ev.get("error") or {}
                raise Retryable("ChatGPT: " + str(err.get("message") or err or "request failed")[:200])
        return {"text": "".join(text), "usage": usage, "images": images}

    def _chat_body(self, model, messages, opts):
        instructions, items = self._input(messages)
        return {"model": model, "instructions": instructions, "input": items}

    # ---- interface
    def list_models(self):
        return [{"id": m, "name": m, "capability": "chat"} for m in chat_models()] + [{"id": IMAGE_MODEL, "name": IMAGE_MODEL, "capability": "image"}]

    def test(self):
        try:
            self.chat(chat_models()[0], [{"role": "user", "content": "Reply with the single word OK."}])
            return {"ok": True, "message": "Connected with your ChatGPT subscription"}
        except ProviderError as e:
            from aistudio.providers.base import scrub
            return {"ok": False, "message": scrub(e, self.secret)[:200]}

    def chat(self, model, messages, opts=None):
        r = self._run(self._chat_body(model, messages, opts))
        if not r["text"].strip():
            raise Retryable("empty answer")
        return {"text": r["text"], "usage": r["usage"], "cost": 0.0, "model": model}

    def vision(self, model, prompt, images, opts=None):
        content = [{"type": "text", "text": prompt}]
        content += [{"type": "image_url", "image_url": {"url": data_url(p)}} for p in images]
        return self.chat(model, [{"role": "user", "content": content}], opts)

    def image(self, model, prompt, refs=(), aspect_ratio="9:16", opts=None):
        w, h = (int(x) for x in aspect_ratio.split(":", 1))
        size = "1024x1536" if w < h else "1536x1024" if w > h else "1024x1024"
        parts = [{"type": "input_text", "text": "Generate an image: " + prompt}]
        parts += [{"type": "input_image", "image_url": data_url(p)} for p in refs]
        body = {"model": chat_models()[0], "instructions": "Use the image_generation tool to create exactly the image requested.",
                "input": [{"type": "message", "role": "user", "content": parts}],
                "tools": [{"type": "image_generation", "size": size}], "tool_choice": {"type": "image_generation"}}
        r = self._run(body)
        if not r["images"]:
            raise Retryable("no image in response")
        return {"bytes": base64.b64decode(r["images"][-1]), "usage": {}, "cost": 0.0, "model": model}
