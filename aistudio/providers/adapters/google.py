"""Google Gemini API (Google AI Studio key): chat, vision, image generation and Veo video.  Standard library only.

Veo request shape re-verified 2026-10-21 at ai.google.dev/gemini-api/docs/veo (REST examples):
  instances[0] = {prompt, image, lastFrame, referenceImages:[{image, referenceType:"asset"}]}; every image is {"inlineData":{"mimeType","data"}}
  (the docs show inlineData, not bytesBase64Encoded, so the start image uses inlineData too). parameters = aspectRatio 16:9|9:16,
  resolution 720p|1080p|4k, durationSeconds 4|6|8 (8 required for reference images, 1080p, 4k, extension).
  lastFrame must be used with image; referenceImages up to 3, not on Veo 3.1 Lite. Agrees with plan 13 notes.
  UNVERIFIED, so refused rather than sent: referenceImages together with image/lastFrame (docs are silent). Not sent: personGeneration
  (docs say allow_adult only for image/interpolation/reference modes; left at the API default), numberOfVideos, camera (Veo has none).
  Other notes: the docs say the veo-3.1 *-preview ids shut down 2026-10-22 (replacement: GA Veo 3.1 on the Gemini Enterprise Agent Platform).
  NOTE: other request/response shapes below are from the public Gemini API; re-check against the live docs before release.
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

from aistudio.providers.base import Adapter, Rejected, Retryable, b64_of, mime_of


class GoogleAdapter(Adapter):
    type = "google"
    capabilities = frozenset({"chat", "vision", "image", "video"})
    default_base_url = "https://generativelanguage.googleapis.com/v1beta"
    request_features = frozenset({"end_frame", "refs"})

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
            if "predictLongRunning" in methods or "generateVideos" in methods or mid.startswith("veo"):
                cap = "video"
            elif ("image" in mid or "imagen" in mid or "generateImages" in methods) and ("generateContent" in methods or "predict" in methods):
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
        # Support up to 14 reference images (as demonstrated in google-flow-mcp)
        clean_refs = list(refs)[:14]
        contents_parts = [{"text": prompt}] + self._inline(clean_refs)
        image_config = {"aspectRatio": aspect_ratio}
        if (opts or {}).get("negative_prompt"):
            image_config["negativePrompt"] = opts["negative_prompt"]
        body = {"contents": [{"role": "user", "parts": contents_parts}],
                "generationConfig": {"responseModalities": ["TEXT", "IMAGE"],
                                     "imageConfig": image_config}}
        data = self._generate(model, body)
        for part in self._parts(data):
            inline = part.get("inlineData") or {}
            if inline.get("data"):
                return {"bytes": base64.b64decode(inline["data"]), "usage": self._usage(data),
                        "cost": None, "model": model}
        raise Retryable("no image in response")

    def image_edit(self, model, image_path, prompt, edit_mode="inpaint_insertion", mask_mode="MASK_MODE_BACKGROUND", opts=None):
        """Natural language inpainting, outpainting or background swapping using Nano Banana Pro / Flash."""
        aspect_ratio = (opts or {}).get("aspect_ratio", "9:16")
        instruction = f"Edit mode: {edit_mode}. Mask mode: {mask_mode}. Instruction: {prompt}"
        body = {"contents": [{"role": "user", "parts": [{"text": instruction}] + self._inline([image_path])}],
                "generationConfig": {"responseModalities": ["TEXT", "IMAGE"],
                                     "imageConfig": {"aspectRatio": aspect_ratio}}}
        data = self._generate(model, body)
        for part in self._parts(data):
            inline = part.get("inlineData") or {}
            if inline.get("data"):
                return {"bytes": base64.b64decode(inline["data"]), "usage": self._usage(data),
                        "cost": None, "model": model}
        raise Retryable("no image in response")

    @staticmethod
    def _veo_image(path):
        return {"inlineData": {"mimeType": mime_of(path), "data": b64_of(path)}}

    def video_submit(self, model, req):
        first, last, refs = req.get("first_frame"), req.get("last_frame"), list(req.get("refs") or [])
        seconds = int(req["seconds"])
        if req.get("camera_native"):
            raise Rejected("Veo has no native camera parameters; put the camera wording in the prompt")
        if last and not first:
            raise Rejected("Veo needs a start image to use an end frame")
        if refs:
            if "lite" in model:
                raise Rejected("Veo 3.1 Lite does not accept reference images")
            if len(refs) > 3:
                raise Rejected("Veo accepts at most 3 reference images, %d given" % len(refs))
            if seconds != 8:
                raise Rejected("Veo reference images need an 8 second clip, %d given" % seconds)
            if first or last:
                raise Rejected("Veo reference images together with a start or end frame are not verified, so they are not sent")
        if req["resolution"] in ("1080p", "4k") and seconds != 8:
            raise Rejected("Veo %s needs an 8 second clip, %d given" % (req["resolution"], seconds))
        inst = {"prompt": req["prompt"]}
        if first:
            inst["image"] = self._veo_image(first)
        if last:
            inst["lastFrame"] = self._veo_image(last)
        if refs:
            inst["referenceImages"] = [{"image": self._veo_image(r), "referenceType": "asset"} for r in refs]
        body = {"instances": [inst],
                "parameters": {"aspectRatio": req["aspect_ratio"],
                               "durationSeconds": seconds,
                               "resolution": req["resolution"]}}
        data = self.transport("POST", self.base_url + "/models/%s:predictLongRunning" % model,
                              headers=self._headers(), body=body)
        return {"job_id": data["name"], "model": model}

    def video_extend(self, model, video_path, prompt, seconds=5, aspect_ratio="16:9", resolution="720p", opts=None):
        """Extend a Veo video clip forward with continuation prompt."""
        inst = {"prompt": prompt,
                "video": {"bytesBase64Encoded": b64_of(video_path), "mimeType": mime_of(video_path) or "video/mp4"}}
        body = {"instances": [inst],
                "parameters": {"aspectRatio": aspect_ratio,
                               "durationSeconds": int(seconds),
                               "resolution": resolution}}
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