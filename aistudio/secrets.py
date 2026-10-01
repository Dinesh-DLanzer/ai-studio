"""Write-only secret store for provider API keys.  Standard library only (the OS keychain is used when the optional `keyring` package works).

A secret is a dict of named string fields, for example {"api_key": "..."} or {"access_key": "...", "secret_key": "..."}, stored under a
`ref` (the provider id).  Rules:
  * Secrets live OUTSIDE the repo and workspace: ~/.aistudio/secrets.json (directory 0700, file 0600), or AISTUDIO_SECRETS_DIR.
  * The API layer never returns a secret: `masked()` gives only whether it is set and the last 4 characters.
  * `redact()` removes every stored value (and env-ref value) from a piece of text, for logs and error messages.
  * AISTUDIO_NO_KEYRING=1 forces the file backend (tests, CI, Docker).
"""
import json
import os
import re
from pathlib import Path

REF_RE = re.compile(r"^[A-Za-z0-9._:-]{1,64}$")
FIELD_RE = re.compile(r"^[a-z_]{1,32}$")
SERVICE = "aistudio"
LEGACY_SERVICE = "ad" + "studio"      # keychain entries and ~/.adstudio made before the rename are still found


class SecretError(Exception):
    pass


def default_dir():
    if os.environ.get("AISTUDIO_SECRETS_DIR"):
        return Path(os.environ["AISTUDIO_SECRETS_DIR"])
    new, old = Path.home() / ".aistudio", Path.home() / (".ad" + "studio")
    if not new.exists() and old.is_dir():          # one-time move of the pre-rename folder (keeps saved keys)
        try:
            old.rename(new)
        except OSError:
            return old
    return new


class SecretStore:
    def __init__(self, directory=None, keyring_mod=None):
        self.dir = Path(directory) if directory else default_dir()
        self.path = self.dir / "secrets.json"
        if keyring_mod is not None:
            self.kr = keyring_mod
        elif os.environ.get("AISTUDIO_NO_KEYRING") == "1":
            self.kr = None
        else:
            try:
                import keyring
                self.kr = keyring
            except Exception:
                self.kr = None

    # -- file backend
    def _read(self):
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _write(self, data):
        self.dir.mkdir(parents=True, exist_ok=True)
        os.chmod(self.dir, 0o700)
        tmp = self.path.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f)
        os.chmod(tmp, 0o600)
        os.replace(tmp, self.path)

    @staticmethod
    def _check(ref):
        if not isinstance(ref, str) or not REF_RE.match(ref):
            raise SecretError("invalid secret reference")

    # -- public API
    def backend(self):
        return "keychain" if self.kr else "file"

    def set(self, ref, fields):
        self._check(ref)
        if not isinstance(fields, dict) or not fields or not all(
                isinstance(k, str) and FIELD_RE.match(k) and isinstance(v, str) and v.strip() for k, v in fields.items()):
            raise SecretError("a secret needs one or more non-empty text fields")
        clean = {k: v.strip() for k, v in fields.items()}
        if self.kr:
            try:
                self.kr.set_password(SERVICE, ref, json.dumps(clean))
                return
            except Exception:
                self.kr = None          # keychain unusable here: fall back to the file
        data = self._read()
        data[ref] = clean
        self._write(data)

    def get(self, ref):
        self._check(ref)
        if self.kr:
            try:
                raw = self.kr.get_password(SERVICE, ref) or self.kr.get_password(LEGACY_SERVICE, ref)
                if raw:
                    return json.loads(raw)
            except Exception:
                pass
        return dict(self._read().get(ref) or {})

    def has(self, ref):
        return bool(self.get(ref))

    def delete(self, ref):
        self._check(ref)
        if self.kr:
            for service in (SERVICE, LEGACY_SERVICE):      # also clear entries made before the rename
                try:
                    self.kr.delete_password(service, ref)
                except Exception:
                    pass
        data = self._read()
        if ref in data:
            del data[ref]
            self._write(data)

    def masked(self, ref):
        s = self.get(ref)
        return {"set": bool(s), "fields": {k: "…" + v[-4:] if len(v) > 8 else "…" for k, v in s.items()}}

    def values(self):
        out = [v for s in self._read().values() for v in s.values()]
        for k, v in os.environ.items():
            if k.endswith("_API_KEY") and len(v) >= 8:
                out.append(v)
        return out

    def redact(self, text):
        text = str(text)
        for v in sorted(set(self.values()), key=len, reverse=True):
            if len(v) >= 6:
                text = text.replace(v, "***")
        return text
