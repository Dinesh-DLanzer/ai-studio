"""Validation and model-specific translation for shot camera direction."""

MOVEMENTS = ("static", "pan-left", "pan-right", "tilt-up", "tilt-down", "dolly-in", "dolly-out",
             "truck-left", "truck-right", "pedestal-up", "pedestal-down", "orbit-left", "orbit-right",
             "crane-up", "crane-down", "zoom-in", "zoom-out", "handheld", "tracking", "fpv", "dolly-zoom")
FRAMINGS = ("extreme-wide", "wide", "medium-wide", "medium", "medium-close", "close-up", "extreme-close-up",
            "over-shoulder", "pov", "insert")
ANGLES = ("eye-level", "low", "high", "dutch", "overhead", "ground")

_MOVE_TEXT = {
    "static": "a static camera", "pan-left": "a pan left", "pan-right": "a pan right",
    "tilt-up": "a tilt up", "tilt-down": "a tilt down", "dolly-in": "a dolly in",
    "dolly-out": "a dolly out", "truck-left": "a truck left", "truck-right": "a truck right",
    "pedestal-up": "a pedestal up", "pedestal-down": "a pedestal down", "orbit-left": "an orbit left",
    "orbit-right": "an orbit right", "crane-up": "a crane up", "crane-down": "a crane down",
    "zoom-in": "a zoom in", "zoom-out": "a zoom out", "handheld": "handheld movement",
    "tracking": "a tracking move", "fpv": "an FPV fly-through", "dolly-zoom": "a dolly zoom",
}
_NATIVE_ALIASES = {
    "pan-left": "pan_left", "pan-right": "pan_right", "tilt-up": "tilt_up", "tilt-down": "tilt_down",
    "dolly-in": "dolly_in", "dolly-out": "dolly_out", "truck-left": "truck_left", "truck-right": "truck_right",
    "pedestal-up": "pedestal_up", "pedestal-down": "pedestal_down", "orbit-left": "orbit_left",
    "orbit-right": "orbit_right", "crane-up": "crane_up", "crane-down": "crane_down",
    "zoom-in": "zoom_in", "zoom-out": "zoom_out", "dolly-zoom": "dolly_zoom",
}


def validate_direction(d):
    """Validate a direction object, raising ValueError for unsupported values."""
    if not isinstance(d, dict):
        raise ValueError("direction must be an object")
    for key, values in (("movement", MOVEMENTS), ("framing", FRAMINGS), ("angle", ANGLES)):
        value = d.get(key)
        if value is not None and value not in values:
            raise ValueError(f"invalid direction {key}: {value}")
    for key in ("preset", "aperture", "focus", "speed", "lighting"):
        if key in d and d[key] is not None and not isinstance(d[key], str):
            raise ValueError(f"direction {key} must be text")
    if d.get("lens_mm") is not None and (not isinstance(d["lens_mm"], (int, float)) or isinstance(d["lens_mm"], bool) or d["lens_mm"] <= 0):
        raise ValueError("direction lens_mm must be a positive number")
    if d.get("motion") is not None and (not isinstance(d["motion"], int) or isinstance(d["motion"], bool) or not 1 <= d["motion"] <= 10):
        raise ValueError("direction motion must be an integer from 1 to 10")
    return d


def describe(direction):
    """Render direction as one consistent, plain-English camera sentence."""
    d = validate_direction(direction)
    parts = []
    if d.get("movement"):
        parts.append(_MOVE_TEXT[d["movement"]])
    if d.get("framing"):
        parts.append(f"{d['framing']} framing")
    if d.get("angle"):
        parts.append(f"{d['angle']} angle")
    if d.get("lens_mm"):
        parts.append(f"{d['lens_mm']:g}mm lens")
    if d.get("aperture"):
        parts.append(d["aperture"] + " aperture")
    if d.get("focus"):
        parts.append("focus " + d["focus"])
    if d.get("speed"):
        parts.append(d["speed"] + " speed")
    if d.get("motion") is not None:
        parts.append(f"subject motion {d['motion']}/10")
    if d.get("lighting"):
        parts.append(d["lighting"] + " lighting")
    return ("Camera: " + ", ".join(parts) + ".") if parts else ""


def split(direction, profile):
    """Return native camera params and prompt text; non-native direction is retained in prompt."""
    d = validate_direction(direction)
    camera = (profile or {}).get("camera", {})
    native_moves = set(camera.get("native", []))
    movement = d.get("movement")
    token = _NATIVE_ALIASES.get(movement)
    param = camera.get("param")
    native = {param: token} if movement and token in native_moves and param and camera.get("mode") == "native" else {}
    prompt_direction = dict(d)
    if native:
        prompt_direction.pop("movement", None)
    return native, describe(prompt_direction)
