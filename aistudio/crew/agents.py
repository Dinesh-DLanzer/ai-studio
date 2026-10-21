"""Agent definitions: catalog/agents/<id>.md = frontmatter + prompt body, strictly validated.

A definition can only list tools the registry allows a crew agent (free or paid class).  An unknown tool, or any approval or
human_only tool, is an error - there is no way to allow-list one.  settings/agents.json can override an agent's prompt and limits
(nothing else: a 'tools' key is an error), clamped to the hard limits below.
"""
import json
import re
from pathlib import Path

from aistudio import tool_registry

BUILTIN_DIR = Path(__file__).resolve().parent.parent.parent / "catalog" / "agents"
ID_RE = re.compile(r"^[a-z][a-z0-9-]{1,40}$")
KEYS = {"id", "name", "version", "role", "tools", "engine", "limits"}
HARD = {"max_steps": 50, "max_tokens": 200000, "max_llm_usd": 5.0}
DIRS = [BUILTIN_DIR]     # tests add a fixtures folder
DEFAULT_LIMITS = {"max_steps": 12, "max_tokens": 20000, "max_llm_usd": 0.25}


class AgentError(ValueError):
    pass


def _scalar(v):
    v = v.strip()
    if v.startswith("[") and v.endswith("]"):
        return [x.strip().strip("'\"") for x in v[1:-1].split(",") if x.strip()]
    if re.fullmatch(r"-?\d+", v):
        return int(v)
    if re.fullmatch(r"-?\d*\.\d+", v):
        return float(v)
    return v.strip("'\"")


def parse(text, where="agent"):
    m = re.match(r"\A---\r?\n(.*?)\r?\n---\r?\n?(.*)\Z", text, re.S)
    if not m:
        raise AgentError(f"{where}: missing --- frontmatter")
    meta, cur = {}, None
    for line in m.group(1).splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line.startswith((" ", "\t")):
            if cur is None or not isinstance(meta.get(cur), dict):
                raise AgentError(f"{where}: unexpected indented line {line.strip()!r}")
            k, _, v = line.strip().partition(":")
            meta[cur][k.strip()] = _scalar(v)
            continue
        k, sep, v = line.partition(":")
        if not sep:
            raise AgentError(f"{where}: bad frontmatter line {line!r}")
        k, cur = k.strip(), k.strip()
        meta[k] = {} if k == "limits" and not v.strip() else _scalar(v)
    return meta, m.group(2).strip()


def _limits(raw, where):
    if not isinstance(raw, dict) or set(raw) - set(HARD):
        raise AgentError(f"{where}: limits may only set {', '.join(HARD)}")
    out = {**DEFAULT_LIMITS, **raw}
    for k, cap in HARD.items():
        v = out[k]
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not 0 < v <= cap:
            raise AgentError(f"{where}: limits.{k} must be a number above 0 and at most {cap}")
    out["max_steps"], out["max_tokens"] = int(out["max_steps"]), int(out["max_tokens"])
    return out


def validate(meta, body, where="agent"):
    unknown = set(meta) - KEYS
    if unknown:
        raise AgentError(f"{where}: unknown frontmatter keys {sorted(unknown)}")
    for k in ("id", "name", "version", "role", "tools"):
        if k not in meta:
            raise AgentError(f"{where}: missing '{k}'")
    if not ID_RE.match(str(meta["id"])):
        raise AgentError(f"{where}: bad id {meta['id']!r}")
    if meta.get("engine", "builtin") != "builtin":
        raise AgentError(f"{where}: only engine 'builtin' is supported")
    if not isinstance(meta["tools"], list) or not meta["tools"] or not all(isinstance(t, str) for t in meta["tools"]):
        raise AgentError(f"{where}: tools must be a non-empty list")
    for t in meta["tools"]:
        if t not in tool_registry.TOOLS:
            raise AgentError(f"{where}: unknown tool '{t}'")
        if t not in tool_registry.crew_tools():
            raise AgentError(f"{where}: tool '{t}' is {tool_registry.cost_class(t)} and can never be given to an agent")
    if not body:
        raise AgentError(f"{where}: the prompt body is empty")
    return {"id": meta["id"], "name": str(meta["name"]), "version": meta["version"], "role": str(meta["role"]), "tools": list(dict.fromkeys(meta["tools"])),
            "engine": "builtin", "limits": _limits(meta.get("limits", {}), where), "prompt": body}


def load_file(path):
    path = Path(path)
    agent = validate(*parse(path.read_text(encoding="utf-8"), path.name), where=path.name)
    if path.stem != agent["id"]:
        raise AgentError(f"{path.name}: id '{agent['id']}' must match the file name")
    return agent


def apply_overrides(agent, overrides):
    """settings/agents.json entry for this agent: only 'prompt' and 'limits'.  Tools can never be added (or changed) here."""
    if not overrides:
        return agent
    if not isinstance(overrides, dict) or set(overrides) - {"prompt", "limits"}:
        raise AgentError(f"{agent['id']}: overrides may only set prompt and limits")
    out = dict(agent)
    if "prompt" in overrides:
        if not isinstance(overrides["prompt"], str) or not overrides["prompt"].strip():
            raise AgentError(f"{agent['id']}: override prompt must be text")
        out["prompt"] = overrides["prompt"].strip()
    if "limits" in overrides:
        out["limits"] = _limits({**agent["limits"], **(overrides["limits"] or {})}, agent["id"])
    return out


def load(agent_id, settings_dir=None, dirs=None):
    if not isinstance(agent_id, str) or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", agent_id):
        raise AgentError(f"invalid agent id: {agent_id!r}")
    for d in (dirs or DIRS):
        f = Path(d) / f"{agent_id}.md"
        if f.is_file():
            ov = {}
            if settings_dir and (Path(settings_dir) / "agents.json").is_file():
                try:
                    allov = json.loads((Path(settings_dir) / "agents.json").read_text(encoding="utf-8"))
                except ValueError:
                    raise AgentError("settings/agents.json is not valid JSON") from None
                if not isinstance(allov, dict):
                    raise AgentError("settings/agents.json must be an object")
                ov = allov.get(agent_id)
            return apply_overrides(load_file(f), ov)
    raise AgentError(f"unknown agent '{agent_id}'")


def list_agents(settings_dir=None, dirs=None):
    return [load(f.stem, settings_dir, dirs) for d in (dirs or DIRS) if Path(d).is_dir() for f in sorted(Path(d).glob("*.md"))]
