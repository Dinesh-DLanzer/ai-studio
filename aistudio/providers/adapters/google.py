"""Google Gemini API (Google AI Studio key): chat, vision, image generation and Veo video.  Standard library only.

NOTE: request/response shapes below are from the public Gemini API; they must be re-checked against the live docs before release.
Subclass of aistudio.providers.base.Adapter (read its docstring first: transport, errors, result shapes).
  type = "google" ; capabilities = {"chat","vision","image","video"} ; default_base_url = "https://generativelanguage.googleapis.com/v1beta"
  Header on EVERY request: {"x-goog-api-key": self.secret["api_key"]}.  URLs are base_url + path.

list_models(): GET /models -> {"models":[{"name":"models/gemini-2.5-flash","displayName":"...","supportedGenerationMethods":[...]}]}.
  id = name without the "models/" prefix. capability: "video" if "predictLongRunning" is in the methods; else "image" if the id contains "image"
  (and "generateContent" is in the methods); else "chat" if "generateContent" is in the methods; models with none of these are skipped.
  name = displayName or id. Keep API order.

chat(model, messages, opts=None): POST /models/{model}:generateContent body:
  {"contents":[{"role": "user" or "model", "parts":[{"text": content}]}...], "generationConfig": {...}}.
  OpenAI-style roles: "assistant" -> "model", "system" messages are removed and joined with "\n\n" into body["systemInstruction"] = {"parts":[{"text": joined}]}
  (omit when none). generationConfig has "maxOutputTokens" (opts max_tokens) and "temperature" (opts temperature) only when given; omit generationConfig when empty.
  Response: candidates[0].content.parts[*].text joined = text. usage = usageMetadata.promptTokenCount / candidatesTokenCount (0 if absent).
  cost None. Blank text -> Retryable("empty answer"). Returns {"text","usage":{"input","output"},"cost":None,"model"}.

vision(model, prompt, images, opts=None): same endpoint; one user content whose parts are the prompt {"text"} followed by one
  {"inlineData":{"mimeType": mime_of(path),"data": b64_of(path)}} per image.

image(model, prompt, refs=(), aspect_ratio="9:16", opts=None): POST /models/{model}:generateContent body
  {"contents":[{"role":"user","parts":[{"text": prompt}] + one inlineData part per ref path]}],
   "generationConfig":{"responseModalities":["TEXT","IMAGE"],"imageConfig":{"aspectRatio": aspect_ratio}}}.
  Response: the first part in candidates[0].content.parts that has inlineData -> base64 decode of inlineData.data = bytes.
  None found -> Retryable("no image in response"). Returns {"bytes","usage":{"input","output"} as in chat,"cost":None,"model"}.

video_submit(model, req): POST /models/{model}:predictLongRunning body
  {"instances":[inst], "parameters":{"aspectRatio": req["aspect_ratio"], "durationSeconds": int(req["seconds"]), "resolution": req["resolution"]}}
  where inst = {"prompt": req["prompt"]} plus, when req.get("first_frame") is a path, "image": {"bytesBase64Encoded": b64_of(path), "mimeType": mime_of(path)}.
  Response {"name": "models/veo-3.1-.../operations/abc"} -> return {"job_id": name, "model": model}.
video_poll(job): GET /{job_id} -> if not body.get("done"): {"status":"pending","error":None,"cost":None}.
  If done and body has "error": {"status":"failed","error": error.get("message") or "generation failed","cost":None}.
  If done and no video uri (see download) is present: failed with error "no video in response". Else {"status":"done","error":None,"cost":None}.
  The video uri is body["response"]["generateVideoResponse"]["generatedSamples"][0]["video"]["uri"].
video_download(job): GET /{job_id} again to find the uri (same path as above; raise Retryable("not finished") if missing), then
  self.transport("GET", uri, headers=<the auth header>, raw=True) and return the bytes.
"""
import base64

from aistudio.providers.base import Adapter, Retryable, b64_of, mime_of


class GoogleAdapter(Adapter):
    type = "google"
    capabilities = frozenset({"chat", "vision", "image", "video"})
    default_base_url = "https://generativelanguage.googleapis.com/v1beta"

    def _headers(self):
        return {"x-goog-api-key": self.secret["api_key"]}

    def _parts(self, body):
        return (((body.get("candidates") or [{}])[0] or {}).get("content") or {}).get("parts") or []

    def _usage(self, body):
        u = body.get("usageMetadata") or {}
        return {"input": u.get("promptTokenCount") or 0, "output": u.get("candidatesTokenCount") or 0}

    def _video_uri(self, body):
        response = (body.get("response") or {}).get("generateVideoResponse") or {}
        for sample in response.get("generatedSamples") or []:
            uri = (sample.get("video") or {}).get("uri")
            if uri:
                return uri
        return None

    def list_models(self):
        data = self.transport("GET", self.base_url + "/models", headers=self._headers())
        out = []
        for m in data.get("models") or []:
            name = m.get("name") or ""
            mid = name[len("models/"):] if name.startswith("models/") else name
            methods = m.get("supportedGenerationMethods") or []
            if "predictLongRunning" in methods:
                cap = "video"
            elif "image" in mid and "generateContent" in methods:
                cap = "image"
            elif "generateContent" in methods:
                cap = "chat"
            else:
                continue
            out.append({"id": mid, "name": m.get("displayName") or mid, "capability": cap})
        return out

    def _generate(self, model, body):
        return self.transport("POST", self.base_url + "/models/%s:generateContent" % model,
                              headers=self._headers(), body=body)

    def _answer(self, model, body):
        data = self._generate(model, body)
        text = "".join(p.get("text") or "" for p in self._parts(data))
        if not text.strip():
            raise Retryable("empty answer")
        return {"text": text, "usage": self._usage(data), "cost": None, "model": model}

    @staticmethod
    def _config(opts):
        config = {}
        if (opts or {}).get("max_tokens") is not None:
            config["maxOutputTokens"] = opts["max_tokens"]
        if (opts or {}).get("temperature") is not None:
            config["temperature"] = opts["temperature"]
        return config

    @staticmethod
    def _inline(refs):
        return [{"inlineData": {"mimeType": mime_of(p), "data": b64_of(p)}} for p in refs]

    def chat(self, model, messages, opts=None):
        system = "\n\n".join(m.get("content") or "" for m in messages if m.get("role") == "system")
        body = {"contents": [{"role": "model" if m.get("role") == "assistant" else "user",
                              "parts": [{"text": m.get("content") or ""}]}
                             for m in messages if m.get("role") != "system"]}
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}
        config = self._config(opts)
        if config:
            body["generationConfig"] = config
        return self._answer(model, body)

    def vision(self, model, prompt, images, opts=None):
        body = {"contents": [{"role": "user", "parts": [{"text": prompt}] + self._inline(images)}]}
        config = self._config(opts)
        if config:
            body["generationConfig"] = config
        return self._answer(model, body)

    def image(self, model, prompt, refs=(), aspect_ratio="9:16", opts=None):
        body = {"contents": [{"role": "user", "parts": [{"text": prompt}] + self._inline(refs)}],
                "generationConfig": {"responseModalities": ["TEXT", "IMAGE"],
                                     "imageConfig": {"aspectRatio": aspect_ratio}}}
        data = self._generate(model, body)
        for part in self._parts(data):
            inline = part.get("inlineData") or {}
            if inline.get("data"):
                return {"bytes": base64.b64decode(inline["data"]), "usage": self._usage(data),
                        "cost": None, "model": model}
        raise Retryable("no image in response")

    def video_submit(self, model, req):
        inst = {"prompt": req["prompt"]}
        first_frame = req.get("first_frame")
        if first_frame:
            inst["image"] = {"bytesBase64Encoded": b64_of(first_frame), "mimeType": mime_of(first_frame)}
        body = {"instances": [inst],
                "parameters": {"aspectRatio": req["aspect_ratio"],
                               "durationSeconds": int(req["seconds"]),
                               "resolution": req["resolution"]}}
        data = self.transport("POST", self.base_url + "/models/%s:predictLongRunning" % model,
                              headers=self._headers(), body=body)
        return {"job_id": data["name"], "model": model}

    def _op(self, job):
        return self.transport("GET", self.base_url + "/" + job["job_id"], headers=self._headers())

    def video_poll(self, job):
        body = self._op(job)
        if not body.get("done"):
            return {"status": "pending", "error": None, "cost": None}
        if body.get("error"):
            return {"status": "failed", "error": body["error"].get("message") or "generation failed", "cost": None}
        if not self._video_uri(body):
            return {"status": "failed", "error": "no video in response", "cost": None}
        return {"status": "done", "error": None, "cost": None}

    def video_download(self, job):
        uri = self._video_uri(self._op(job))
        if not uri:
            raise Retryable("not finished")
        return self.transport("GET", uri, headers=self._headers(), raw=True)