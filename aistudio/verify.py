"""Verification of every artifact (brief, story, assets, shots, todos): fast deterministic RULES (free, offline, run on every edit)
plus an AI reviewer prompt/parser (the AI call itself lives in the service). Standard library only.

A finding: {"where": "s03" | "brief.language" | ..., "severity": "high|medium|low", "issue": str, "fix": str}
A result:  {"status": "ok|warn|fail", "findings": [...], "source": "rules|ai|rules+ai", "model": str, "summary": str}
  fail = at least one high finding; warn = medium/low findings; ok = none.
"""
import hashlib
import json
import re

from aistudio import languages as L
from aistudio.storyboard import convert as story_mod

SCOPES = ("brief", "story", "assets", "shots", "todos")
SEV = ("high", "medium", "low")
HEX = re.compile(r"#[0-9a-fA-F]{6}\b")
EMPTY_CENTER = re.compile(r"empty (centre|center|space)|space for (a |the )?logo|blank (centre|center)|room for (a |the )?logo", re.I)
CLAIMS = re.compile(r"guarantee|100\s?%|#\s?1\b|number one|best in (the )?(city|town|world|india)|risk[- ]free|no\.?\s?1", re.I)
PEOPLE = re.compile(r"\b(person|people|man|woman|crowd|customers?|owner|boy|girl|child|children|family)\b", re.I)
LINE = re.compile(r'AUDIO:.*?"([^"]+)"', re.S)


def f(where, severity, issue, fix=""):
    return {"where": where, "severity": severity, "issue": issue, "fix": fix}


def status_of(findings):
    return "fail" if any(x["severity"] == "high" for x in findings) else ("warn" if findings else "ok")


def result(findings, source="rules", model="", summary=""):
    order = {s: i for i, s in enumerate(SEV)}
    findings = sorted(findings, key=lambda x: order.get(x["severity"], 9))
    return {"status": status_of(findings), "findings": findings, "source": source, "model": model,
            "summary": summary or (f"{len(findings)} finding(s)" if findings else "No problems found")}


def content_hash(*parts):
    return hashlib.sha256(json.dumps(parts, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")).hexdigest()[:16]


def _voice_checks(where, line, language, seconds):
    out = []
    words = len(line.split())
    if seconds and words > seconds * 3 + 2:
        out.append(f(where, "medium", f"The spoken line has {words} words, which is long for a {seconds}s clip.", "Use one short sentence (about 8 words or fewer for 4 seconds)."))
    r = L.script_ratio(line, language)
    if r is not None and r < 0.5:
        out.append(f(where, "high", f"The voice line is not written in {language} script (for example Tanglish or English letters).",
                     f"Write the line in {language} script and put the English meaning in brackets."))
    elif r is None and L.canonical(language) in L.LANGUAGES and not L.LANGUAGES[L.canonical(language)][0]:
        lr = L.latin_ratio(line)
        if lr is not None and lr < 0.5:
            out.append(f(where, "medium", f"The voice line does not look like {language} (it uses a different script).", f"Write it in {language}."))
    if CLAIMS.search(line):
        out.append(f(where, "medium", "The spoken line makes an absolute or guaranteed claim.", "Remove guarantees and superlatives; show results visually instead."))
    return out


def lint_shots(shots_doc, images_doc=None, stills=(), language="", scope_where=""):
    out, stills = [], set(stills)
    ids = {i["id"] for i in (images_doc or {}).get("images", [])}
    for s in shots_doc.get("shots", []):
        w, prompt = s.get("id", "?"), s.get("prompt", "")
        if HEX.search(prompt):
            out.append(f(w, "medium", "The prompt contains a colour code (like #07363c). The video model draws it on screen as text.", "Name the colour instead (for example 'deep teal and warm gold')."))
        if EMPTY_CENTER.search(prompt):
            out.append(f(w, "medium", "The prompt asks for an empty centre or space for a logo. The video model often fills it with a person.", "Describe the scene itself; add the logo in the editor."))
        if ("same face" in prompt.lower() or "first frame" in prompt.lower()) and not s.get("first_frame"):
            out.append(f(w, "high", "The prompt relies on a first frame but the shot has none, so the model will invent a new person.", "Attach a first-frame image (Assets tab) and set first_frame."))
        elif s.get("first_frame"):
            stem = re.sub(r"\.[^.]+$", "", s["first_frame"].split("/")[-1])
            if stem not in stills:
                out.append(f(w, "low", f"The first frame {s['first_frame']} has not been created yet.", "Upload or generate it before making the clip."))
            if ids and stem not in ids:
                out.append(f(w, "medium", f"The first frame {stem} is not in the image list.", "Add it to the image list or fix the name."))
        has_audio_line = "AUDIO:" in prompt
        if s.get("audio") and not has_audio_line:
            out.append(f(w, "medium", "Audio is on but the prompt has no spoken line, so the clip will have random sound.", "Add an AUDIO line or switch audio off."))
        if has_audio_line and s.get("audio") is False:
            out.append(f(w, "medium", "The prompt has a spoken line but audio is off, so it will be silent.", "Turn audio on or remove the AUDIO line."))
        m = LINE.search(prompt)
        if m:
            out += _voice_checks(w, m.group(1), language, s.get("seconds"))
        if "veo" in (s.get("model") or "").lower() and s.get("seconds") not in (4, 6, 8):
            out.append(f(w, "high", f"Veo only makes 4, 6 or 8 second clips, not {s.get('seconds')}.", "Choose 4, 6 or 8 seconds."))
        if CLAIMS.search(prompt):
            out.append(f(w, "medium", "The prompt makes an absolute or guaranteed claim.", "Remove it; show results visually."))
        if "no on-screen text" not in prompt.lower() and "no text" not in prompt.lower():
            out.append(f(w, "low", "The prompt does not forbid on-screen text, so garbled text may appear.", "Add 'NEGATIVE: no on-screen text, no subtitles, no logos'."))
    return out


def lint_assets(images_doc, stills=(), brief=None):
    out, stills = [], {re.sub(r"\.[^.]+$", "", x) for x in stills}
    imgs = images_doc.get("images", [])
    by = {i["id"]: i for i in imgs}
    vertical = bool(re.search(r"9:16|reel|short|vertical|tiktok|story", str((brief or {}).get("platform", "")), re.I))
    for i in imgs:
        w, kind, prompt = i["id"], i.get("kind"), i.get("prompt", "")
        if kind == "character" and not re.search(r"expression|happy|sad|angry|neutral", prompt, re.I):
            out.append(f(w, "low", "A character sheet should include facial expressions, so scenes can reuse the face.", "Add 'with a grid of expressions' to the prompt."))
        if kind == "background" and PEOPLE.search(prompt) and "empty" not in prompt.lower():
            out.append(f(w, "low", "A background should be an empty place; this prompt mentions people.", "Say 'empty, no people'."))
        if kind == "frame":
            refs = i.get("refs", [])
            if not refs:
                out.append(f(w, "medium", "This scene frame has no references, so faces and places will not match the other images.", "Pick its character and background as references."))
            else:
                if not any(by.get(r, {}).get("kind") == "character" for r in refs):
                    out.append(f(w, "medium", "This scene frame has no character reference.", "Add the character sheet as a reference."))
                for r in refs:
                    if r in by and r not in stills:
                        out.append(f(w, "low", f"Reference {r} has no image yet.", f"Create {r} first."))
            if vertical and i.get("aspect_ratio") not in (None, "9:16"):
                out.append(f(w, "low", "The platform is vertical but this frame is not 9:16.", "Set the aspect ratio to 9:16."))
        for r in i.get("refs", []):
            if r not in by:
                out.append(f(w, "high", f"The reference {r} does not exist.", "Remove it or add that asset."))
    return out


def lint_brief(brief, language="", required_missing=()):
    out = []
    if required_missing:
        out.append(f("brief", "low", "Still to answer: " + ", ".join(required_missing) + ".", "Answer them in the chat or the Brief panel."))
    lang = L.canonical(language or brief.get("language", ""))
    if lang:
        inf = L.info(lang)
        if not inf["known"]:
            out.append(f("brief.language", "low", f"'{lang}' is not in the language list.", "Pick a listed language, or keep it and test a clip first."))
        elif not inf["tested"]:
            out.append(f("brief.language", "medium", f"{lang} has not been tested with the video model.", f"Make one cheap test clip and have a native {lang} speaker listen before making the rest."))
    cap = re.sub(r"[^0-9.]", "", str(brief.get("budget_cap", "")))
    length = re.sub(r"[^0-9]", "", str(brief.get("length_seconds", "")))
    try:
        if cap and length:
            minimum = (int(length) / 4) * 0.12
            if float(cap) < minimum:
                out.append(f("brief.budget_cap", "medium", f"A {length}s video needs at least about ${minimum:.2f} even with no retries and no audio.", "Raise the cap or shorten the video."))
        if length and int(length) > 60:
            out.append(f("brief.length_seconds", "medium", "Videos over 60 seconds get expensive and hard to keep consistent.", "Split it into shorter videos."))
    except ValueError:
        pass
    for k in ("story", "goal"):
        if CLAIMS.search(str(brief.get(k, ""))):
            out.append(f(f"brief.{k}", "medium", "This text makes an absolute or guaranteed claim.", "Avoid guarantees in a video."))
    return out


def lint_story(md, brief=None, language=""):
    out = []
    try:
        st = story_mod.parse_story(md or "")
    except ValueError:
        return [f("Story.md", "low", "The storyboard has no '## Shot' sections yet.", "Use the chat to draft one, or write it in the template format.")]
    lang = language or (brief or {}).get("language", "")
    for s in st["shots"]:
        w = s["id"]
        if not s["prompt"]:
            out.append(f(w, "high", "This shot has no AI Video Prompt.", "Write the prompt (subject, action, camera, lighting, style)."))
        if s["voice_mode"] != "silent" and not s["voice_line"]:
            out.append(f(w, "medium", "The voice mode says someone speaks but there is no voice line.", "Write the line or mark the shot SILENT."))
        if s["voice_line"]:
            out += _voice_checks(w, s["voice_line"], lang, 4)
            if not s["english"] and L.canonical(lang) != "English":
                out.append(f(w, "low", "There is no English meaning for the voice line.", "Add it under **English** so reviewers can check the translation."))
        if s["voice_mode"] == "on-camera" and not s["image"]:
            out.append(f(w, "medium", "A character speaks on camera but the shot has no image.", "Add an **Image** id so the face stays consistent."))
        if not s["image"] and PEOPLE.search(s["prompt"]):
            out.append(f(w, "medium", "The prompt has people but no image id, so Veo may invent someone.", "Add an **Image** id."))
        if s["on_screen_text"] and any(t and t.lower() in s["prompt"].lower() for t in s["on_screen_text"]):
            out.append(f(w, "low", "On-screen text appears inside the video prompt; the model will draw it badly.", "Keep on-screen text out of the prompt; add it in the editor."))
    target = re.sub(r"[^0-9]", "", str((brief or {}).get("length_seconds", "")))
    if target and not (0.5 * int(target) <= 4 * len(st["shots"]) <= 2 * int(target)):
        out.append(f("Story.md", "low", f"{len(st['shots'])} shots of 4s is about {4 * len(st['shots'])}s, far from the {target}s you asked for.", "Add or remove shots."))
    brand = str((brief or {}).get("brand", "")).split(",")[0].strip().lower()
    if brand and brand.split()[0] not in (md or "").lower():
        out.append(f("Story.md", "low", f"The brand '{brand}' is not mentioned in the storyboard.", "Check the storyboard matches the brief."))
    return out


def lint_todos(manual):
    out, seen = [], set()
    for t in manual:
        key = t["title"].strip().lower()
        if key in seen:
            out.append(f(t["id"], "low", f"Duplicate task: {t['title']}", "Remove one."))
        seen.add(key)
    if sum(1 for t in manual if not t["done"]) > 15:
        out.append(f("todos", "low", "More than 15 open tasks.", "Close or remove tasks you will not do."))
    return out


# ---------------------------------------------------------------- AI reviewer protocol
AI_SYSTEM = """You are a meticulous QA reviewer for AI-generated video projects. You check ONE artifact (brief, story, assets, shots or todos)
against the brief and the project language. Be concrete and brief. Do not invent problems: if it is fine, say so.

Things that matter: the voice lines are in the chosen language and its own script (Tamil must be Tamil script, not English letters) with an English meaning;
one short sentence per clip; every shot with people has an image of those characters (otherwise the video model invents a person); no colour codes, logos,
on-screen text or 'empty space for a logo' in video prompts; no absolute claims (guaranteed, #1, 100%); consistent names, characters and places across
the brief, story, assets and shots; realistic length and budget; assets have references so faces and places match; tasks are specific and not duplicated.

Answer with ONE JSON object and nothing else:
{"verdict": "pass|warn|fail", "summary": "<one sentence>", "findings": [{"where": "<id or field>", "severity": "high|medium|low", "issue": "<what is wrong>", "fix": "<how to fix it>"}]}
Use "fail" only for problems that would waste money or break the video. The automatic rule checks already found the issues listed below; do not repeat them."""


def build_ai_messages(scope, artifact, brief, language, rule_findings):
    body = {"scope": scope, "project_language": language or "not set", "brief": {k: v for k, v in (brief or {}).items() if v},
            "already_found_by_rules": [f"{x['where']}: {x['issue']}" for x in rule_findings][:20], "artifact": artifact}
    return [{"role": "system", "content": AI_SYSTEM}, {"role": "user", "content": json.dumps(body, ensure_ascii=False)[:14000]}]


def parse_ai(text):
    """Extract the verdict JSON. Never raises. Returns {"findings": [...], "summary": str, "ok": bool}."""
    t = (text or "").strip()
    dec = json.JSONDecoder()
    for m in re.finditer(r"\{", t):
        try:
            obj, _ = dec.raw_decode(t[m.start():])
        except ValueError:
            continue
        if isinstance(obj, dict) and isinstance(obj.get("findings"), list):
            fs = []
            for x in obj["findings"][:25]:
                if isinstance(x, dict) and isinstance(x.get("issue"), str) and x["issue"].strip():
                    sev = x.get("severity") if x.get("severity") in SEV else "low"
                    fs.append(f(str(x.get("where", ""))[:60], sev, x["issue"].strip()[:400], str(x.get("fix", ""))[:400]))
            return {"findings": fs, "summary": str(obj.get("summary", ""))[:300], "ok": True}
    return {"findings": [], "summary": "The AI reviewer's answer could not be read.", "ok": False}
