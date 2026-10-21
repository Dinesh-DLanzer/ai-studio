"""Price cards for models, estimates and computed cost.  Standard library only.

A price card describes what one model costs:
  video: {"kind":"video","per_second": {"720p": <rate>, ...}}    <rate> is whatever rates.py understands (number | {"audio","no_audio"} | tiers)
  image: {"kind":"image","per_image": 0.036}
  text:  {"kind":"text","input_per_1m": 0.1, "output_per_1m": 0.4}   or {"kind":"text","free": true}
Card sources, first match wins:  user override (settings/models.json) > built-in rates.json (OpenRouter ids) > built-in fake models > none.
No card = UNKNOWN price.  Image/video with an unknown price must never run (the engine refuses until the user sets a price); text with an
unknown price is only allowed when "allow paid" is on and is logged as source "unknown".

Cost sources:  "reported" (the provider said so) > "computed" (usage x card) > "estimated" (card price for the request, no usage info).
"""
import json
from datetime import date
from pathlib import Path

from aistudio import rates as rates_mod

KEY_SEP = "|"
META = ("retrieved_at", "source")
STALE_DAYS = 30
FLAT_RATE = ("chatgpt", "codex_cli", "claude_cli", "agy_cli")


def key(provider_id, model):
    return f"{provider_id}{KEY_SEP}{model}"


FAKE_CARDS = {
    "fake/video": {"kind": "video", "per_second": {"720p": {"audio": 0.05, "no_audio": 0.03}, "480p": {"audio": 0.05, "no_audio": 0.03}}},
    "fake/image": {"kind": "image", "per_image": 0.036},
    "fake/llm": {"kind": "text", "free": True}, "fake/vision": {"kind": "text", "per_call": 0.001},
}


def _iso_date(v):
    try:
        return date.fromisoformat(v) if isinstance(v, str) and len(v) == 10 else None
    except ValueError:
        return None


def validate_card(card):
    """Returns a list of problems ([] = valid). Optional on any card: minimum_seconds, per_reference_image, retrieved_at (ISO date), source."""
    kinds = ("video", "image", "text", "audio", "utility")      # audio / utility: shape only, later plans add behaviour
    if not isinstance(card, dict) or card.get("kind") not in kinds:
        return ["kind must be video, image or text"]
    num = lambda v: isinstance(v, (int, float)) and not isinstance(v, bool) and v >= 0
    errs = [f"{f} must be a number >= 0" for f in ("minimum_seconds", "per_reference_image") if f in card and not num(card[f])]
    if "retrieved_at" in card and not _iso_date(card["retrieved_at"]):
        errs.append("retrieved_at must be an ISO date (YYYY-MM-DD)")
    if "source" in card and not isinstance(card["source"], str):
        errs.append("source must be text")
    k = card["kind"]
    if k == "image":
        errs += [] if num(card.get("per_image")) else ["per_image must be a number >= 0"]
    elif k == "audio":
        errs += [] if num(card.get("per_1k_chars")) or num(card.get("per_minute")) else ["audio needs per_1k_chars or per_minute (a number >= 0)"]
    elif k == "utility":
        errs += [] if num(card.get("per_run")) else ["per_run must be a number >= 0"]
    elif k == "video":
        ps = card.get("per_second")
        if not isinstance(ps, dict) or not ps:
            errs.append("per_second needs at least one resolution")
        else:
            for res, d in ps.items():
                try:
                    rates_mod.rate_for({"models": {"m": {res: d}}}, "m", res, 4, True)
                except (KeyError, ValueError, TypeError):
                    errs.append(f"per_second for {res} is not a valid rate")
                    break
    elif not (card.get("free") is True or num(card.get("per_call")) or (num(card.get("input_per_1m")) and num(card.get("output_per_1m")))):
        errs.append("text needs free, per_call, or input_per_1m and output_per_1m")
    return errs


class Pricing:
    def __init__(self, legacy_rates=None, overrides=None):
        self.rates, self.meta = {}, {}      # the meta keys never reach rates.rate_for, so the math is unchanged
        for m, d in (legacy_rates or {}).get("models", {}).items():
            self.rates[m] = {k: v for k, v in d.items() if k not in META}
            self.meta[m] = {k: v for k, v in d.items() if k in META}
        self.image_rates = (legacy_rates or {}).get("image_models", {})
        self.overrides = overrides or {}

    @classmethod
    def load(cls, rates_path, settings_dir):
        try:
            legacy = json.loads(Path(rates_path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            legacy = {}
        try:
            ov = json.loads((Path(settings_dir) / "models.json").read_text(encoding="utf-8")).get("prices", {})
        except (OSError, ValueError):
            ov = {}
        return cls(legacy, ov)

    def card(self, provider_id, ptype, model):
        c = self.overrides.get(key(provider_id, model))
        if c:
            return c
        # ComfyUI workflow models (wf:<id>) are always free
        if model.startswith("wf:"):
            return {"kind": "video", "per_second": {"720p": 0.0, "480p": 0.0}, "free": True}
        if ptype == "fake" and model in FAKE_CARDS:
            return FAKE_CARDS[model]
        if ptype == "openrouter":
            if model in self.rates:
                return {"kind": "video", "per_second": self.rates[model], **self.meta[model]}
            if model in self.image_rates:
                return {"kind": "image", "per_image": self.image_rates[model]}
            if model.endswith(":free") or model == "openrouter/free":
                return {"kind": "text", "free": True}
        if ptype == "opencode_cli" and model.endswith("-free"):      # other OpenCode models bill per token: price unknown until the user sets it
            return {"kind": "text", "free": True}
        if ptype in FLAT_RATE:              # flat-rate plan or local CLI: no per-token or per-image fee (a price set by the user still wins above)
            if model.startswith(("gpt-image", "dall-e")):
                return {"kind": "image", "per_image": 0.0}
            return {"kind": "text", "free": True}
        return None

    def suggest(self, model):
        """A price card we know for a similar model id (for example the OpenRouter price of the same Veo model), to offer as a one-click default."""
        base = model.split("/")[-1]
        best = None
        for mid, ps in self.rates.items():
            name = mid.split("/")[-1]
            if base == name or base.startswith(name + "-") or name.startswith(base + "-"):
                if best is None or len(name) > len(best[0]):          # the most specific match wins (veo-3.1-lite beats veo-3.1)
                    best = (name, {"kind": "video", "per_second": ps, "from": mid})
        return best[1] if best else None

    # -- prices
    def video_price(self, card, seconds, resolution="720p", audio=False, refs=0):
        if not card or card.get("kind") != "video":
            return None
        try:
            billed = max(int(seconds), int(card.get("minimum_seconds") or 0))
            base = rates_mod.clip_cost({"models": {"m": card["per_second"]}}, "m", resolution, billed, bool(audio))
        except (KeyError, ValueError):
            return None
        return round(base + int(refs) * float(card.get("per_reference_image") or 0), 6)

    def task_price(self, card, seconds, resolution="720p", refs=0):
        """Price of a paid clip tool: a utility card's per_run, else the video card's per-second rate x the source seconds. None = unknown."""
        if card and card.get("kind") == "utility":
            return round(float(card["per_run"]), 6)
        return self.video_price(card, seconds, resolution, refs=refs)

    def image_price(self, card, refs=0):
        if not card or card.get("kind") != "image":
            return None
        return round(float(card["per_image"]) + int(refs) * float(card.get("per_reference_image") or 0), 6)

    @staticmethod
    def age_days(card, today=None):
        """Days since the card's retrieved_at, or None when it has no (valid) date."""
        d = _iso_date((card or {}).get("retrieved_at"))
        return (today or date.today()).toordinal() - d.toordinal() if d else None

    def age_warning(self, card, today=None):
        """'' when the price is fresh, else a sentence for the approver. A warning only, never a block."""
        age = self.age_days(card, today)
        if age is None:
            return "Price card has no date; check it is current before approving."
        return f"Price card is {age} days old (retrieved {card['retrieved_at']}); check it is current." if age > STALE_DAYS else ""

    def breakdown(self, card, seconds=0, resolution="720p", audio=False, refs=0, today=None):
        """What a quote is made of: base (rate x billed seconds, or per_image), minimum_applied, refs charge, audio flag, total (== the quote), card date and age."""
        out = {"base": None, "minimum_applied": False, "refs": 0.0, "audio": bool(audio), "total": None,
               "retrieved_at": (card or {}).get("retrieved_at"), "age_days": self.age_days(card, today), "source": (card or {}).get("source")}
        if not card:
            return out
        total = self.image_price(card, refs) if card.get("kind") == "image" else self.video_price(card, seconds, resolution, audio, refs)
        if total is None:
            return out
        out["refs"] = round(int(refs) * float(card.get("per_reference_image") or 0), 6)
        out["base"], out["total"] = round(total - out["refs"], 6), total
        if card.get("kind") == "video":
            out["minimum_applied"] = int(seconds) < int(card.get("minimum_seconds") or 0)
            out["billed_seconds"] = max(int(seconds), int(card.get("minimum_seconds") or 0))
        return out

    def is_free(self, card):
        if card and card.get("kind") == "image":
            return card.get("per_image") == 0
        if card and card.get("kind") == "video":
            def zero(v):
                return v == 0 if isinstance(v, (int, float)) else all(zero(x) for x in (v.values() if isinstance(v, dict) else [t.get("rate") for t in v]))
            return bool(card.get("per_second")) and zero(card["per_second"])
        return bool(card and card.get("kind") == "text" and card.get("free"))

    def text_cost(self, card, usage):
        if not card or card.get("kind") != "text":
            return None
        if card.get("free"):
            return 0.0
        if "per_call" in card:
            return float(card["per_call"])
        # Adapters commonly normalize missing usage to zero counts. A paid
        # completion with no positive counts is not evidence of a free call.
        if not usage or not any(usage.get(k) for k in ("input", "output")):
            return None
        u = usage
        return round((u.get("input", 0) * card["input_per_1m"] + u.get("output", 0) * card["output_per_1m"]) / 1_000_000, 6)

    def actual_cost(self, reported, computed):
        """-> (cost, source). `computed` may be None."""
        if reported is not None:
            return float(reported), "reported"
        if computed is not None:
            return float(computed), "computed"
        return 0.0, "unknown"
