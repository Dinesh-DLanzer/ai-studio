"""whisper.cpp: local, free speech-to-text with word timestamps.  Standard library only.

Subclass of aistudio.providers.base.Adapter (read its docstring first).
  type = "whisper_cpp" ; capabilities = {"transcribe"} ; no API key, no network, no cost.
  The CONNECTION carries two fields (they live in the secret dict like every other provider field):
    "binary"     : path or name of the whisper.cpp binary.  Default discovery: shutil.which("whisper-cli"),
                   then shutil.which("whisper-cpp").
    "model_path" : path of the ggml model file (e.g. models/ggml-base.en.bin).  Required to transcribe.

  Every call runs two LOCAL programs, always with an argv list (never a shell):
    1. ffmpeg converts the audio to the format whisper.cpp wants: 16 kHz, mono, 16-bit PCM wav.
       The command is the one in whisper.cpp's README ("ffmpeg -i input.mp3 -ar 16000 -ac 1 -c:a pcm_s16le
       output.wav"); the cli example only reads 16-bit wav files.
    2. the whisper.cpp binary writes its result as JSON:
         whisper-cli -m <model> -f <wav> [-l <language>] [-t <threads>] -ojf -of <prefix> -np
       -ojf / --output-json-full is verified in whisper.cpp's examples/cli/cli.cpp: it sets output_jsn and
       also wparams.token_timestamps, so the JSON carries a timestamp for every token.
       -of / --output-file takes the path WITHOUT the extension: the JSON lands in "<prefix>.json".
       -np / --no-prints only drops the timing summary; -l / --language sets the spoken language.
    The JSON shape (also from examples/cli/cli.cpp):
       {"result": {"language": "en"}, "params": {...},
        "transcription": [{"text": "...", "offsets": {"from": 0, "to": 11000},
                           "tokens": [{"text": " And", "offsets": {"from": 0, "to": 320}, ...}]}]}
       "offsets" are MILLISECONDS (whisper.cpp keeps centiseconds and writes t * 10).

  transcribe(model, audio_path, opts=None) -> {"text", "words": [{"text","start","end"}], "language"}
    "start" / "end" are SECONDS.  The words come from the per-token timestamps, so they are whisper word
    pieces, not always whole words.  "model" is ignored unless it points at an existing model file.
    opts: "workdir"/"project_dir" (where the temporary folder goes), "language", "threads", "timeout",
          "ffmpeg" (the ffmpeg program), "model_path" (overrides the connection).
  test(): the binary must exist and "--help" must run.  Never raises.
  Errors: binary or model file missing -> AuthError ; ffmpeg or the binary refused the file -> Rejected ;
    timeout -> Retryable.

  The program runner is injectable for tests: conn["runner"](cmd, cwd, timeout) -> (returncode, stdout, stderr).

  Both programs run in a temporary folder INSIDE the project (opts["workdir"] / opts["project_dir"]); the
  folder is deleted again when the call ends.  Without a project folder the system temp folder is used.

  UNVERIFIED: this adapter was written against whisper.cpp's master README and examples/cli/cli.cpp, but
  no whisper.cpp build was run here (the binary is not installed on the machine that wrote this file), so
  the flag spellings and the JSON keys are read from the source, not from a live run.  The fallback binary
  name "whisper-cpp" is a guess (whisper.cpp builds "whisper-cli"; older builds were named differently).
"""
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from aistudio.providers.base import Adapter, AuthError, Rejected, Retryable, scrub

DEFAULT_TIMEOUT = 900
BINARY_CANDIDATES = ("whisper-cli", "whisper-cpp")
HELP_TIMEOUT = 30


def default_run(cmd, cwd=None, timeout=DEFAULT_TIMEOUT):
    """Run a local program.  argv list only, no shell, stdin closed, output captured."""
    try:
        p = subprocess.run(list(cmd), capture_output=True, text=True, cwd=cwd, timeout=timeout,
                           stdin=subprocess.DEVNULL, check=False)
    except FileNotFoundError:
        raise AuthError(f"{Path(cmd[0]).name} is not installed or not in PATH") from None
    except subprocess.TimeoutExpired:
        raise Retryable(f"{Path(cmd[0]).name} timed out after {timeout}s") from None
    except OSError as e:
        raise Retryable(f"could not start {Path(cmd[0]).name}: {e}") from None
    return p.returncode, p.stdout or "", p.stderr or ""


def _tail(text, n=200):
    return " ".join(str(text or "").split())[-n:]


def parse_transcript(doc):
    """whisper.cpp --output-json-full JSON -> {"text", "words": [{"text","start","end"}], "language"}.

    "start"/"end" are seconds; the text is whisper's own segment text (the token list would put a space
    in front of every comma).  Tokens without a timestamp are dropped.
    """
    doc = doc or {}
    segments = doc.get("transcription") or []
    words = []
    for seg in segments:
        for tok in seg.get("tokens") or []:
            off = tok.get("offsets") or {}
            if "from" not in off or "to" not in off:
                continue
            text = str(tok.get("text") or "").strip()
            if not text:
                continue
            words.append({"text": text,
                          "start": round(float(off["from"]) / 1000.0, 3),
                          "end": round(float(off["to"]) / 1000.0, 3)})
    text = "".join(str(seg.get("text") or "") for seg in segments).strip()
    if not text:
        text = " ".join(w["text"] for w in words).strip()
    language = (doc.get("result") or {}).get("language") or (doc.get("params") or {}).get("language") or ""
    return {"text": text, "words": words, "language": language}


class WhisperCppAdapter(Adapter):
    type = "whisper_cpp"
    capabilities = frozenset({"transcribe"})
    task_methods = frozenset({"transcribe"})

    def __init__(self, conn, transport=None, run=None):
        super().__init__(conn, transport)
        self.run = run or conn.get("runner") or default_run

    # ---------------------------------------------------------------- the local setup
    def binary_path(self):
        """The whisper.cpp binary: the configured path, else PATH lookup of whisper-cli then whisper-cpp."""
        configured = str(self.secret.get("binary") or "").strip()
        if configured:
            p = Path(configured).expanduser()
            if p.exists():
                return str(p)
            return shutil.which(configured)          # a bare name that is on PATH
        for name in BINARY_CANDIDATES:
            found = shutil.which(name)
            if found:
                return found
        return None

    def model_file(self, model=None, opts=None):
        """The ggml model file: opts, then the connection, then "model" when it points at an existing file."""
        for cand in ((opts or {}).get("model_path"), self.secret.get("model_path")):
            cand = str(cand or "").strip()
            if cand:
                return Path(cand).expanduser()   # the configured path wins, even when the file is missing
        cand = str(model or "").strip()
        if cand:
            p = Path(cand).expanduser()
            if p.exists():
                return p
        return None

    def ffmpeg_path(self, opts=None):
        """The ffmpeg program (needed to convert the audio to the 16 kHz mono wav whisper.cpp reads)."""
        given = str((opts or {}).get("ffmpeg") or "").strip()
        if given:
            p = Path(given).expanduser()
            return str(p) if p.exists() else (shutil.which(given) or given)
        return shutil.which("ffmpeg")

    def list_models(self):
        return [{"id": "whisper-cpp", "name": "whisper.cpp (local model)", "capability": "transcribe"}]

    def test(self):
        try:
            exe = self.binary_path()
            if not exe:
                return {"ok": False, "message": "whisper.cpp binary not found (install whisper.cpp or set the binary path)"}
            rc, out, err = self.run([exe, "--help"], None, HELP_TIMEOUT)
            if rc != 0:
                return {"ok": False, "message": f"{Path(exe).name} --help failed: {_tail(err or out, 120)}"}
            model = self.model_file()
            if model is None:
                return {"ok": True, "message": f"Found {Path(exe).name} (no model file set yet)"}
            if not model.exists():
                return {"ok": False, "message": f"whisper.cpp model file not found: {model}"}
            return {"ok": True, "message": f"Found {Path(exe).name} and {model.name}"}
        except Exception as e:
            return {"ok": False, "message": scrub(e, self.secret)[:200]}

    # ---------------------------------------------------------------- transcription
    def transcribe(self, model, audio_path, opts=None):
        opts = opts or {}
        exe = self.binary_path()
        if not exe:
            raise AuthError("whisper.cpp binary not found (install whisper.cpp or set the binary path)")
        model_file = self.model_file(model, opts)
        if model_file is None:
            raise AuthError("no whisper.cpp model file is set for this provider")
        if not model_file.exists():
            raise AuthError(f"whisper.cpp model file not found: {model_file}")
        src = Path(str(audio_path)).expanduser()
        if not src.exists():
            raise Rejected(f"audio file not found: {src}")

        timeout = opts.get("timeout") if isinstance(opts.get("timeout"), (int, float)) and opts.get("timeout") > 0 else DEFAULT_TIMEOUT
        work = self._workdir(opts)
        try:
            wav = self._to_wav(src, work, opts, timeout)
            prefix = str(Path(work) / "transcript")
            cmd = [exe, "-m", str(model_file), "-f", str(wav)]
            language = str(opts.get("language") or "").strip()
            if language:
                cmd += ["-l", language]
            if opts.get("threads"):
                cmd += ["-t", str(int(opts["threads"]))]
            cmd += ["-ojf", "-of", prefix, "-np"]
            rc, out, err = self.run(cmd, str(work), timeout)
            if rc != 0:
                raise Rejected(f"whisper.cpp failed: {_tail(err or out)}")
            jf = Path(prefix + ".json")
            if not jf.exists():
                raise Retryable("whisper.cpp wrote no JSON output")
            try:
                doc = json.loads(jf.read_text(encoding="utf-8"))
            except ValueError:
                raise Retryable("whisper.cpp wrote JSON that could not be read") from None
            return parse_transcript(doc)
        finally:
            shutil.rmtree(work, ignore_errors=True)

    # ---------------------------------------------------------------- helpers
    def _workdir(self, opts):
        """A temporary folder inside the project (never outside it)."""
        base = opts.get("workdir") or opts.get("project_dir") or self.conn.get("project_dir")
        if base:
            base = Path(str(base)).expanduser()
            base.mkdir(parents=True, exist_ok=True)
            return Path(tempfile.mkdtemp(prefix="whisper-", dir=str(base)))
        return Path(tempfile.mkdtemp(prefix="aistudio-whisper-"))

    def _to_wav(self, src, work, opts, timeout):
        """ffmpeg: 16 kHz, mono, 16-bit PCM wav (what the whisper.cpp cli example reads)."""
        ffmpeg = self.ffmpeg_path(opts)
        if not ffmpeg:
            raise AuthError("ffmpeg is not installed (it is needed to convert the audio to 16 kHz mono wav)")
        dst = Path(work) / "audio16k.wav"
        cmd = [ffmpeg, "-y", "-nostdin", "-hide_banner", "-loglevel", "error", "-i", str(src),
               "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", str(dst)]
        rc, out, err = self.run(cmd, str(work), timeout)
        if rc != 0 or not dst.exists():
            raise Rejected(f"ffmpeg could not convert the audio: {_tail(err or out)}")
        return dst
