"""Voice languages: names, scripts, and how well each is tested with Veo 3.1 Lite. Standard library only."""
import re

# name -> (unicode ranges of its own script or None for Latin-script languages, tested)
LANGUAGES = {
    "English": (None, True), "Tamil": ([(0x0B80, 0x0BFF)], True),
    "Hindi": ([(0x0900, 0x097F)], False), "Marathi": ([(0x0900, 0x097F)], False), "Telugu": ([(0x0C00, 0x0C7F)], False),
    "Kannada": ([(0x0C80, 0x0CFF)], False), "Malayalam": ([(0x0D00, 0x0D7F)], False), "Bengali": ([(0x0980, 0x09FF)], False),
    "Gujarati": ([(0x0A80, 0x0AFF)], False), "Punjabi": ([(0x0A00, 0x0A7F)], False), "Urdu": ([(0x0600, 0x06FF)], False),
    "Arabic": ([(0x0600, 0x06FF)], False), "Spanish": (None, False), "French": (None, False), "German": (None, False),
    "Portuguese": (None, False), "Italian": (None, False), "Indonesian": (None, False), "Russian": ([(0x0400, 0x04FF)], False),
    "Japanese": ([(0x3040, 0x30FF), (0x4E00, 0x9FFF)], False), "Korean": ([(0xAC00, 0xD7AF)], False), "Chinese": ([(0x4E00, 0x9FFF)], False),
}
NAMES = list(LANGUAGES)


def canonical(name):
    """'tamil' / ' Tamil ' -> 'Tamil'. Unknown names are kept as typed (a user-defined language)."""
    n = (name or "").strip()
    for k in LANGUAGES:
        if k.lower() == n.lower():
            return k
    return n


def info(name):
    n = canonical(name)
    script, tested = LANGUAGES.get(n, (None, False))
    return {"name": n, "known": n in LANGUAGES, "tested": tested, "script": bool(script)}


def script_ratio(text, name):
    """Share of the LETTERS in `text` that belong to the language's own script (None for Latin-script or unknown languages)."""
    script = LANGUAGES.get(canonical(name), (None, False))[0]
    if not script:
        return None
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return None
    hit = sum(1 for c in letters if any(lo <= ord(c) <= hi for lo, hi in script))
    return hit / len(letters)


def latin_ratio(text):
    letters = [c for c in text if c.isalpha()]
    return (sum(1 for c in letters if c.isascii()) / len(letters)) if letters else None


def split_languages(text):
    return [canonical(x) for x in re.split(r"[,;/&]| and ", text or "") if x.strip()]
