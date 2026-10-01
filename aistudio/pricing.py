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
from pathlib import Path

from aistudio import rates as rates_mod

KEY_SEP = "|"


def key(provider_id, model):
    return f"{provider_id}{KEY_SEP}{model}"


FAKE_CARDS = {
    "fake/video": {"kind": "video", "per_second": {"720p": {"audio": 0.05, "no_audio": 0.03}, "480p": {"audio": 0.05, "no_audio": 0.03}}},
    "fake/image": {"kind": "image", "per_image": 0.036},
    "fake/llm": {"kind": "text", "free": True}, "fake/vision": {"kind": "text", "per_call": 0.001},
}


def validate_card(card):
    """Returns a list of problems ([] = valid)."""
    if not isinstance(card, dict) or card.get("kind") not in ("video", "image", "text"):
        return ["kind must be video, image or text"]
    num = lambda v: isinstance(v, (int, float)) and not isinstance(v, bool) and v >= 0
    k = card["kind"]
    if k == "image":
        return [] if num(card.get("per_image")) else ["per_image must be a number >= 0"]
    if k == "video":
        ps = card.get("per_second")
        if not isinstance(ps, dict) or not ps:
            return ["per_second needs at least one resolution"]
        for res, d in ps.items():
            try:
                rates_mod.rate_for({"models": {"m": {res: d}}}, "m", res, 4, True)
            except (KeyError, ValueError, TypeError):
                return [f"per_second for {res} is not a valid rate"]
        return []
    if card.get("free") is True or num(card.get("per_call")):
        return []
    return [] if num(card.get("input_per_1m")) and num(card.get("output_per_1m")) else ["text needs free, per_call, or input_per_1m and output_per_1m"]


class Pricing:
    def __init__(self, legacy_rates=None, overrides=None):
        self.rates = (legacy_rates or {}).get("models", {})
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
        if ptype == "fake" and model in FAKE_CARDS:
            return FAKE_CARDS[model]
        if ptype == "openrouter":
            if model in self.rates:
                return {"kind": "video", "per_second": self.rates[model]}
            if model in self.image_rates:
                return {"kind": "image", "per_image": self.image_rates[model]}
            if model.endswith(":free") or model == "openrouter/free":
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
    def video_price(self, card, seconds, resolution="720p", audio=False):
        if not card or card.get("kind") != "video":
            return None
        try:
            return rates_mod.clip_cost({"models": {"m": card["per_second"]}}, "m", resolution, int(seconds), bool(audio))
        except (KeyError, ValueError):
            return None

    def image_price(self, card):
        return float(card["per_image"]) if card and card.get("kind") == "image" else None

    def is_free(self, card):
        return bool(card and card.get("kind") == "text" and card.get("free"))

    def text_cost(self, card, usage):
        if not card or card.get("kind") != "text":
            return None
        if card.get("free"):
            return 0.0
        if "per_call" in card:
            return float(card["per_call"])
        u = usage or {}
        return round((u.get("input", 0) * card["input_per_1m"] + u.get("output", 0) * card["output_per_1m"]) / 1_000_000, 6)

    def actual_cost(self, reported, computed):
        """-> (cost, source). `computed` may be None."""
        if reported is not None:
            return float(reported), "reported"
        if computed is not None:
            return float(computed), "computed"
        return 0.0, "unknown"
