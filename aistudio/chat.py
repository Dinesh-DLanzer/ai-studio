"""Producer chat: an AI that interviews the user (story concept, brief) and keeps the TODO list, focused ONLY on making the video.

Design:
  * The chat model must be FREE ("...:free" or "openrouter/free"). Chat turns cost $0, so they need no approval; a paid chat model is refused
    unless the user turned on 'Allow paid models' in Settings (their explicit choice).
  * The model answers with ONE JSON object per turn: {"reply", "brief_updates", "todos_add", "storyboard_md"}. Nothing the model says spends money or
    touches shots/images: a storyboard it writes is only stored as a PENDING proposal; the human clicks "Apply".
  * Fake mode uses a deterministic scripted interviewer (no network), so the whole flow is testable for $0.
Standard library only.
"""
import json
import re

from aistudio.storyboard import convert as story_mod

# (key, label, question, required)
BRIEF_FIELDS = [
    ("brand", "Brand / business", "What is the brand or business name, and what does it sell or do?", True),
    ("goal", "Goal", "What should this video achieve (for example: get walk-ins, sell a product, launch an offer)?", True),
    ("story", "Story concept", "Tell me the story in a few sentences: what happens from the first second to the last?", True),
    ("audience", "Audience", "Who is it for (who should feel 'that's for me')?", False),
    ("platform", "Platform", "Where will it run: Instagram Reels / YouTube Shorts (9:16) or YouTube (16:9)?", False),
    ("length_seconds", "Length (seconds)", "How long should the final video be? (Each generated clip is 4, 6 or 8 seconds.)", True),
    ("language", "Voice language", "Which language should the voice speak (for example English or Tamil)?", True),
    ("extra_languages", "Other languages", "Do you also want versions in other languages? (optional)", False),
    ("characters", "Characters", "Does anyone appear in the video? If yes, give each person a name, age range, look and clothes. (Say \"none\" if nobody does.)", True),
    ("setting", "Setting / places", "Where does it take place? Describe each place. (Say \"none\" for an abstract video.)", True),
    ("cta", "Call to action", "What should viewers do at the end (and what exact words)?", False),
    ("brand_assets", "Brand assets", "Do you have a logo or other files to use? Press the image button in the chat box to attach them. Should the video use your brand colours (I can read them from your logo)?", False),
    ("claims_to_avoid", "Claims to avoid", "Anything we must NOT claim or show (guarantees, prices, competitors)?", False),
    ("budget_cap", "Budget cap (USD)", "What is the most you are willing to spend on generating this video (in dollars)?", True),
]
FIELD_KEYS = [f[0] for f in BRIEF_FIELDS]
MAX_VALUE = 1500

FREE_MODELS = ["nvidia/nemotron-3-ultra-550b-a55b:free", "qwen/qwen3.8-27b:free", "google/gemma-4-31b-it:free", "openrouter/free"]


def chat_models():
    return list(FREE_MODELS)


def is_free(model):
    return model.endswith(":free") or model == "openrouter/free"


def check_chat_models(models, allow_paid=None):
    """Refuse paid models unless the user allowed them (Settings > Usage & Limits)."""
    if allow_paid:
        return models
    paid = [m for m in models if not is_free(m)]
    if paid:
        raise ValueError(f"chat models must be free (':free'); refusing {paid}. Turn on 'Allow paid models' in Settings to allow them.")
    return models


def missing(brief, required_only=True):
    return [k for k, _, _, req in BRIEF_FIELDS if (req or not required_only) and not str(brief.get(k, "")).strip()]


def progress(brief):
    req = [k for k, _, _, r in BRIEF_FIELDS if r]
    done = [k for k in req if str(brief.get(k, "")).strip()]
    return {"required_done": len(done), "required_total": len(req), "missing": missing(brief), "complete": not missing(brief)}


def clean_updates(updates):
    """Keep only known fields with short string values."""
    out = {}
    for k, v in (updates or {}).items():
        if k in FIELD_KEYS and isinstance(v, (str, int, float)) and str(v).strip():
            out[k] = str(v).strip()[:MAX_VALUE]
    return out


def render_brief_md(name, brief):
    lines = [f"# Brief: {name}", ""]
    for k, label, _, req in BRIEF_FIELDS:
        if k == "extra_languages":
            continue
        v = str(brief.get(k, "")).strip()
        lines.append(f"- **{label}**{' (required)' if req else ''}: {v or '_not answered yet_'}")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- real model protocol
SYSTEM = """You are TARA, the PRODUCER in AI Studio. Your name is Tara; say so when you introduce yourself. You help a person make a short AI-generated VIDEO (an ad, a story, an explainer, a music clip, anything) and you talk about nothing else.
Your job: (1) interview them to fill in the brief, (2) keep the TODO list, (3) when the brief is complete, draft the storyboard.

Rules:
- AI Studio makes ANY kind of video: an ad, a short story, an explainer, a music or festival clip, a tutorial, a personal film. Never assume it is an advertisement. Treat the brief field "brand" as the title, subject or brand (whatever the video is about) and "goal" as its purpose (for example tell a story, explain something, entertain, promote a product). Ask about customers, offers or calls to action only if the video is promotional.
- Never assume a language. The voice language is whatever the user chooses (English, Tamil, Hindi or any other); only use a language that the user said or that is already filled in the brief state. Reply in the language the user writes in. In your first message, greet them briefly as Tara and ask what video they want to make; do not mention a language, a brand or an ad unless they did.
- Work in this order: BRIEF first, then STORY, then TODO. Keep interviewing until every required brief field is filled; do NOT write the storyboard before that. In the same message where the last required field is filled, write the full storyboard in "storyboard_md" and list the story-specific tasks in "todos_add". The storyboard is saved as Story.md and the tasks as TODO.md automatically, so tell the user briefly what you saved.
- Ask at most TWO short questions per message. Be friendly, brief, practical. Use the person's language for replies when they write in another language.
- Required brief fields: brand, goal, story, length_seconds, language, characters, setting, budget_cap. Optional: audience, platform, cta, brand_assets (logo file and brand colours), claims_to_avoid.
- Never invent facts about the business: ask. Never promise results. Do not claim guaranteed sales or reach.
- Video facts you must respect: one short sentence of speech per clip; clips are 4, 6 or 8 seconds; the voice line is written in the chosen language's own script (for example Tamil script for Tamil) plus an English meaning, and an English video needs no separate translation line beyond the same text; on-screen text, logos and end cards are added later in an editor, never generated; every shot with people needs an image of those characters.
- You cannot spend money, and you cannot generate, approve, upload, apply or edit anything yourself. The page has buttons for all of that, each with its own price approval. NEVER say that you generated, approved, uploaded, applied, saved or edited something unless the project state below shows it. Facts about progress come ONLY from "Current project state": if the user says they did something that the state does not show yet, say kindly that it is not done yet and point to the button.
- Production order is fixed (the page enforces it): 1 brief, 2 storyboard (Story.md), 3 budget approval, 4 character images, 5 background images, 6 scene frames (one per shot), 7 video clips, 8 approve clips, 9 Review & Export. No clip can be made before its scene frame, and no scene frame before the characters and places it uses. When the user asks for a later step too early, explain which step comes first (the state's "next_step_for_the_user" says exactly what it is) instead of pretending to do it.
- Budget: if budget.approved is true, NEVER ask for budget approval again. If a storyboard is applied and budget.approved is false, tell the user ONCE to press "Set the budget" (or the checklist button) and do not repeat it.
- Before you draft the storyboard, make sure you asked (in your normal two-questions-per-message pace) about: who appears (characters, "none" is fine), the places (backgrounds, "none" is fine), files to use such as a logo or product photo (tell them to press the image button in the chat box; the project state lists attached files under "uploads" with their main colours) and whether the video should use their brand colours. If they say yes and "uploads" has colours, use exactly those hex colours; if they name colours, use those.
- If the user later changes the plan (a new character, place, logo or colours, another shot) put the FULL updated storyboard in "storyboard_md" again so Story.md can be updated; do not just describe the change.
- When ALL required fields are filled, draft the storyboard in the exact Markdown format below and put it in "storyboard_md".

Answer with ONE JSON object and nothing else:
{"reply": "<your message to the user>", "brief_updates": {"<field>": "<value>"}, "todos_add": ["<short task>"], "storyboard_md": null}
- brief_updates: only fields the user just told you (use their words, tidy).
- todos_add: at most 6 short extra tasks that are specific to THIS video (the moment you write the storyboard, add the tasks that story needs: assets to gather, voice checks, edits) (for example "Get the real shop logo file"). Do not repeat generic steps.
- storyboard_md: null until the brief is complete, then the full storyboard.

Storyboard Markdown format (follow exactly; one "## Shot NN" block per shot, 4 seconds each unless told otherwise).
The sections before the shots become the project's assets: each "### <Name>" under Characters / Backgrounds becomes one master image to generate, "Shared style" is added to EVERY image prompt, and a shot's "**Uses**" line lists which characters, places and uploaded files its scene frame needs (use the lowercase_underscore version of the names; an uploaded file is used by its id from the state's uploads).
# <BRAND>: AI VIDEO STORYBOARD
## Shared style
<one or two sentences: the look, lighting and colour palette used in every image and clip; include the brand hex colours when the user agreed>
## Characters
### <Name>
<age range, look, clothes, expression; one short paragraph. Leave the whole "## Characters" section out if nobody appears>
## Backgrounds
### <Place name>
<one short paragraph. Leave the whole "## Backgrounds" section out if there are no places>
## Shot 01 — 0:00–0:04
### Purpose: HOOK
**Visual**
<what we see>
**Camera**
<one camera move>
**Action**
<one action>
**Voice** (ON-CAMERA)        (use ON-CAMERA if a character speaks to camera, OFF-CAMERA for narration, SILENT for none)
> <one short sentence, in the voice language's script>
**English**
> <the English meaning>
**On-screen text**
> <text added later in the editor>
**Uses**: <names of the characters / places / uploaded files in this shot, comma separated, for example ramesh, shop_front, logo>
**Image**: <image id, for example s01>
**AI Video Prompt**
> SUBJECT: ... ACTION: ... CAMERA: ... LIGHTING: ... STYLE: cinematic, realistic and believable (adapt the style to the brief). NEGATIVE: no other person, no on-screen text, no subtitles, no logos, no background music, no watermark, no distorted faces or hands.
"""


TEST_NOTE = (
    "\n\nTEST PIPELINE: this project is a practice run. You (the chat AI) are real, but every other step is simulated for free by a built-in test AI: "
    "the character, background and scene images are plain placeholder pictures, the video clips are placeholder files that cannot be played as real footage, "
    "the AI review of the storyboard, assets and shots is skipped (only the automatic rule checks run), and nothing costs real money (test prices are tiny). "
    "The workflow is otherwise identical to a real project: chat to fill the brief, apply the storyboard, set and approve a budget, generate each image and "
    "each clip one at a time with a price approval, then approve or discard. When the user asks how anything works, explain that process step by step "
    "and say which parts are simulated here and what would be different with real models (real pictures and playable clips, real cost, the AI review). "
    "Still interview them properly so the brief and storyboard come out as good as a real one. Placeholder images and clips are made only when the user presses the generate buttons."
)


def prefs_note(prefs):
    """The user's choices from the chat sidebar, as one short system note. Unknown or oversized values are ignored."""
    if not isinstance(prefs, dict):
        return ""
    bits = []
    if prefs.get("aspect") in ("16:9", "9:16", "1:1"):
        bits.append(f"aspect ratio {prefs['aspect']}")
    if isinstance(prefs.get("style"), str) and 0 < len(prefs["style"]) <= 40:
        bits.append(f"visual style: {prefs['style']}")
    if isinstance(prefs.get("references"), int) and 0 < prefs["references"] <= 50:
        bits.append(f"{prefs['references']} reference image(s) uploaded as assets")
    out = ("\nThe user chose: " + "; ".join(bits) + ".") if bits else ""
    if prefs.get("auto_storyboard") is True:
        out += " As soon as the required brief fields are answered, draft the storyboard without asking again."
    elif prefs.get("auto_storyboard") is False:
        out += " Do not draft the storyboard until the user asks for it."
    note = prefs.get("notes")
    if isinstance(note, str) and note.strip():
        out += " Extra instructions from the user: " + note.strip()[:600]
    return out


def attach_note(files):
    """One line telling the model which images the user attached (and their main colours)."""
    if not files:
        return ""
    bits = [f"{f['id']} (saved in Uploads" + (f"; main colours {', '.join(f['colors'])}" if f.get("colors") else "") + ")" for f in files]
    return "\n\n[The user attached image(s): " + "; ".join(bits) + ". You cannot see them, but they are saved as project assets.]"


def build_messages(history, user_text, state, test_pipeline=False, prefs=None, files=None):
    """state = the project's real, current facts (see Workspace._chat_state): the model must rely on it, never on guesses."""
    msgs = [{"role": "system", "content": SYSTEM + (TEST_NOTE if test_pipeline else "") + prefs_note(prefs) + "\nCurrent project state (JSON): " + json.dumps(state, ensure_ascii=False)}]
    for h in history[-16:]:
        msgs.append({"role": "assistant" if h["role"] == "assistant" else "user", "content": h["text"] + (attach_note(h.get("attachments")) if h["role"] != "assistant" else "")})
    msgs.append({"role": "user", "content": user_text + attach_note(files)})
    return msgs


_TOKEN_RE = re.compile(r"<\|[^|>]*\|>")           # special tokens some models leak, e.g. <|tool_call_start|>
_KEYS = {"reply": "reply", "message": "reply", "brief_updates": "brief_updates", "todos_add": "todos_add", "todos": "todos_add",
         "storyboard_md": "storyboard_md", "storyboard": "storyboard_md"}


def _balanced(t, start):
    """Index just after the bracket group that opens at t[start] ((, [ or {), skipping quoted strings; None if it never closes."""
    pairs, stack, q, esc = {"(": ")", "[": "]", "{": "}"}, [], None, False
    for i in range(start, len(t)):
        c = t[i]
        if q:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == q:
                q = None
            continue
        if c in "'\"":
            q = c
        elif c in pairs:
            stack.append(pairs[c])
        elif stack and c == stack[-1]:
            stack.pop()
            if not stack:
                return i + 1
    return None


def recover(text):
    """Some free models answer with a pseudo tool call (write_storyboard(storyboard_md='...', brief_updates={...})) or a Python-style dict instead of the
    JSON object we asked for.  Pull the fields out of those safely (ast.literal_eval only; nothing is executed).  Returns a dict or None."""
    import ast
    t = _TOKEN_RE.sub("", text or "")
    for m in re.finditer(r"([A-Za-z_][A-Za-z_0-9]*)\s*\(|\{", t):
        start = m.end() - 1 if m.group(1) else m.start()
        end = _balanced(t, start)
        if end is None:
            continue
        chunk = t[m.start():end]
        try:
            node = ast.parse(chunk.strip(), mode="eval").body
        except (SyntaxError, ValueError, MemoryError, RecursionError):
            continue
        found = {}
        try:
            if isinstance(node, ast.Call):
                for kw in node.keywords:
                    if kw.arg in _KEYS:
                        found[_KEYS[kw.arg]] = ast.literal_eval(kw.value)
            elif isinstance(node, ast.Dict):
                for k, v in zip(node.keys, node.values):
                    if isinstance(k, ast.Constant) and k.value in _KEYS:
                        found[_KEYS[k.value]] = ast.literal_eval(v)
        except (ValueError, SyntaxError):
            continue
        if found:
            return found
    return None


def _turn(obj, reply=None, **extra):
    sm = obj.get("storyboard_md")
    r = reply if reply is not None else str(obj.get("reply") or "").strip()
    return {"reply": r, "brief_updates": clean_updates(obj.get("brief_updates") if isinstance(obj.get("brief_updates"), dict) else None),
            "todos_add": [str(x).strip()[:120] for x in (obj.get("todos_add") or []) if isinstance(x, (str, int)) and str(x).strip()][:6] if isinstance(obj.get("todos_add"), list) else [],
            "storyboard_md": sm if isinstance(sm, str) and sm.strip() else None, **extra}


def parse_turn(text):
    """Extract the turn from a model answer.  Never raises.  Order: the JSON object we asked for; a pseudo tool call / Python-style dict (recovered);
    plain words (the model just chatted).  `malformed` is True when the answer looked like structured output we could not read, so the caller can ask again."""
    t = (text or "").strip()
    dec = json.JSONDecoder()
    for m in re.finditer(r"\{", t):
        try:
            obj, _ = dec.raw_decode(t[m.start():])
        except ValueError:
            continue
        if isinstance(obj, dict) and isinstance(obj.get("reply"), str):
            return _turn(obj, malformed=False)
    rec = recover(t)
    if rec:
        reply = str(rec.get("reply") or "").strip() or ("I drafted the storyboard." if rec.get("storyboard_md") else "Got it.")
        return _turn(rec, reply=reply, malformed=False, recovered=True)
    plain = _TOKEN_RE.sub("", t).strip()
    looks_structured = bool(_TOKEN_RE.search(t)) or bool(re.search(r"\b(storyboard_md|brief_updates|todos_add|tool_call)\b", t)) or plain[:1] in "{[("
    return {"reply": plain[:2000] or "Sorry, I could not answer that. Please try again.", "brief_updates": {}, "todos_add": [], "storyboard_md": None, "malformed": looks_structured}


def unreadable(text):
    """True for an old saved answer that is raw tool-call output rather than words for the user."""
    return bool(_TOKEN_RE.search(text or "")) or bool(re.search(r"\bwrite_storyboard\(|storyboard_md\s*=", text or ""))


RETRY_NOTE = ("Your last answer could not be read. Answer again with EXACTLY ONE JSON object and nothing else: no tool calls, no code fences, no special tokens. "
              'Keys: "reply", "brief_updates", "todos_add", "storyboard_md". If you write the storyboard, it must use the exact Markdown format from the instructions '
              '("## Shot 01 — 0:00–0:04" headings and **bold** labels).')


def valid_storyboard(md):
    try:
        st = story_mod.parse_story(md)
    except ValueError:
        return False
    return 1 <= len(st["shots"]) <= 12


# ---------------------------------------------------------------- test mode: deterministic scripted interviewer
_NONE = ("none", "no", "nobody", "nothing", "n/a", "-", "skip")


def _slug(name):
    return re.sub(r"[^a-z0-9]+", "_", str(name).lower()).strip("_")[:40] or "item"


def build_story_md(brief):
    """A complete storyboard from the brief alone: shared style, characters, backgrounds, and one frame per shot that says what it uses."""
    brand = brief.get("brand", "Brand")
    n = max(1, min(6, round(int(re.sub(r"\D", "", str(brief.get("length_seconds", "8"))) or 8) / 4)))
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", brief.get("story", "")) if s.strip()] or [brief.get("story", "")]
    chars = str(brief.get("characters", "")).strip()
    setting = str(brief.get("setting", "")).strip()
    assets = str(brief.get("brand_assets", ""))
    colors = re.findall(r"#[0-9a-fA-F]{6}", assets)
    logo = (re.search(r"[Ll]ogo file:\s*([A-Za-z0-9_-]+)", assets) or [None, ""])[1]
    has_char, has_place = chars.lower() not in _NONE and chars != "", setting.lower() not in _NONE and setting != ""
    cname = (re.split(r"[,.(:\u2014-]", chars)[0].strip() or "Main character")[:40] if has_char else ""
    cid, bid = (_slug(cname) if has_char else ""), ("main_place" if has_place else "")
    style = "Cinematic, realistic and believable, natural light." + (f" Brand colours: {', '.join(colors)} used in the clothes, props and light." if colors else "")
    lines = [f"# {brand}: AI VIDEO STORYBOARD", "", "## Concept", f"**Brand:** {brand}", f"**Language:** {brief.get('language', 'English')}", "",
             "## Shared style", style, ""]
    if has_char:
        lines += ["## Characters", f"### {cname}", chars, ""]
    if has_place:
        lines += ["## Backgrounds", "### Main place", setting, ""]
    for i in range(n):
        s = sentences[min(i, len(sentences) - 1)]
        purpose = "HOOK" if i == 0 else ("CTA" if i == n - 1 and n > 1 else "STORY")
        voice = brief.get("cta", s) if purpose == "CTA" else s
        uses = [x for x in (cid, bid, logo if (purpose == "CTA" or n == 1) else "") if x]
        subject = (cname if has_char else "the scene")
        lines += [f"## Shot {i + 1:02d} — 0:{i * 4:02d}–0:{i * 4 + 4:02d}", f"### Purpose: {purpose}", "", "**Visual**", f"{s}" + (f" ({setting})" if has_place else ""), "",
                  "**Camera**", "Slow push-in.", "", "**Action**", f"{subject} acts out: {s}", "", "**Voice** (ON-CAMERA)" if has_char else "**Voice** (OFF-CAMERA)", f"> {voice}", "",
                  "**English**", f"> {voice}", "", "**On-screen text**", f"> {brand.upper()}", "",
                  *([f"**Uses**: {', '.join(uses)}", ""] if uses else []), f"**Image**: s{i + 1:02d}", "", "**AI Video Prompt**",
                  f"> SUBJECT: {subject}, same face and clothes as the first frame. ACTION: {s} CAMERA: slow push-in. LIGHTING: natural light. "
                  "STYLE: cinematic, realistic and believable (adapt the style to the brief). NEGATIVE: no other person, no on-screen text, no subtitles, "
                  "no logos, no background music, no watermark, no distorted faces or hands.", ""]
    return "\n".join(lines)


def scripted_turn(brief, history, user_text, files=None):
    """Test-mode interviewer: the user's message answers the question that was asked last; then ask the next one (required fields, then the
    logo / brand-colour question once).  An attached image is remembered as the logo, with its colours."""
    asked = next((h.get("asked") for h in reversed(history) if h["role"] == "assistant" and h.get("asked")), None)
    updates = {}
    if asked and user_text.strip().lower() not in ("skip", "-"):
        updates[asked] = user_text.strip()[:MAX_VALUE]
    elif asked == "brand_assets":
        updates[asked] = "none"
    if files:
        f = files[0]
        updates["brand_assets"] = (updates.get("brand_assets", "") + f" Logo file: {f['id']}." + (f" Brand colours: {', '.join(f['colors'])}." if f.get("colors") else "")).strip()[:MAX_VALUE]
    merged = {**brief, **updates}
    need = missing(merged)              # only REQUIRED fields are asked; optional ones can be filled in the Brief panel
    if not need and not str(merged.get("brand_assets", "")).strip() and not any(h.get("asked") == "brand_assets" for h in history):
        q = next(q for k, _, q, _ in BRIEF_FIELDS if k == "brand_assets")
        return {"reply": q + " (Say \"skip\" if you have none.)", "brief_updates": updates, "todos_add": [], "storyboard_md": None, "asked": "brand_assets"}
    if not need:
        lang = merged.get("language", "the chosen language")
        return {"reply": "I have everything I need. I drafted the storyboard from your brief.",
                "brief_updates": updates, "storyboard_md": build_story_md(merged), "asked": None,
                "todos_add": [f"Have a {lang} speaker check every voice line", "Collect reference photos for the characters and places", "Plan the final edit: trim, text, music"]}
    nxt = need[0]
    q = next(q for k, _, q, _ in BRIEF_FIELDS if k == nxt)
    greeting = "Hi! I'm Tara, your producer. I'll ask a few questions, then draft your storyboard. " if not history else ""
    return {"reply": greeting + q, "brief_updates": updates, "todos_add": [], "storyboard_md": None, "asked": nxt}
