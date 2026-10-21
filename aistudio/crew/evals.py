"""Deterministic evaluation suite for AI Studio Crew agents (Plan 28 section 3.7).

Runs evaluation cases from catalog/evals/crew/*.json through the real crew runtime in a temp
test project (fake image/video providers). Refuses to run against a paid chat model unless
allow_paid=True is explicitly passed, and shows max LLM spend first.

Scoring is deterministic:
  1. Storyboard shot count within format
  2. Format aspect ratio matches expected
  3. Voice lines present in the project language/script (using aistudio.languages)
  4. Every shot has a valid model per the catalog
  5. Documents validate against schemas (ShotsDoc, etc.)
  6. Proposals only (no approvals or forbidden tools attempted/executed)
  7. Paid batch total <= budget cap
"""
import fnmatch
import json
import os
import shutil
import time
import uuid
from pathlib import Path

from aistudio import languages as lang_mod, project_lock, tool_registry
from aistudio.crew import agents as crew_agents, stages, runtime
from aistudio.domain.common import ServiceError
from aistudio.schemas.storyboard import ShotsDoc, ImagesDoc, EditDoc

BUILTIN_CASES_DIR = Path(__file__).resolve().parent.parent.parent / "catalog" / "evals" / "crew"


def load_cases(cases_dir=None):
    """Load and return all evaluation cases from catalog/evals/crew/*.json."""
    d = Path(cases_dir or BUILTIN_CASES_DIR)
    if not d.is_dir():
        return []
    cases = []
    for f in sorted(d.glob("*.json")):
        try:
            c = json.loads(f.read_text(encoding="utf-8"))
            if isinstance(c, dict) and "id" in c:
                cases.append(c)
        except (ValueError, OSError):
            continue
    return cases


def get_case(case_id, cases_dir=None):
    cases = load_cases(cases_dir)
    hit = next((c for c in cases if c["id"] == case_id), None)
    if not hit:
        raise ServiceError(f"unknown eval case '{case_id}'")
    return hit


def is_valid_catalog_model(catalog, model_name):
    """Check if model_name is a valid video model pattern or known model in catalog."""
    if not model_name or not isinstance(model_name, str):
        return False
    if model_name.startswith("fake/video") or model_name.startswith("fake/"):
        return True
    if hasattr(catalog, "entries"):
        for e in catalog.entries:
            pat = e.get("pattern", "")
            if pat == "*":
                continue
            tasks = e.get("profile", {}).get("tasks", [])
            if any("video" in t for t in tasks):
                if fnmatch.fnmatchcase(model_name, pat):
                    return True
    if getattr(catalog, "pricing", None) and hasattr(catalog.pricing, "rates"):
        if model_name in catalog.pricing.rates:
            return True
    return False


def is_paid_chat_model(ws, model_name=None):
    """Check if a chat model is a paid model."""
    if model_name and (model_name.startswith("fake/") or model_name.endswith(":free") or model_name == "openrouter/free"):
        return False
    try:
        entries = ws.runner().resolve("chat", None)
        if entries and (not model_name or entries[0].get("model") == model_name):
            card = entries[0].get("card")
            if card:
                return not ws.pricing().is_free(card)
        if model_name:
            card = ws.pricing().card(None, None, model_name)
            if card:
                return not ws.pricing().is_free(card)
            return True
    except Exception:
        pass
    return False


def estimate_max_llm_spend(ws, cases, stage="write_storyboard"):
    """Estimate total upper-bound LLM spend across cases."""
    S = stages.STAGES.get(stage, {})
    steps = S.get("steps", [])
    try:
        agent_defs = [crew_agents.load(a, ws.settings_dir) for a, _ in steps]
        per_case = sum(a["limits"]["max_llm_usd"] for a in agent_defs)
    except Exception:
        per_case = 0.75
    return round(per_case * len(cases), 6)


def evaluate_project(ws, project, case, run_rec):
    """Perform deterministic structure checks on the completed run in project. Returns check dict and pass status."""
    p = ws.pdir(project)
    expected = case.get("expected", {})
    brief = case.get("brief", {})
    checks = {}

    # 1. Storyboard shot count
    shots_doc = ws._read(p, "shots.json", {"shots": []})
    shots = shots_doc.get("shots", [])
    n_shots = len(shots)
    min_shots = expected.get("min_shots", 1)
    max_shots = expected.get("max_shots", 99)
    if min_shots <= n_shots <= max_shots:
        checks["shot_count"] = {"ok": True, "detail": f"{n_shots} shots (expected {min_shots}..{max_shots})"}
    else:
        checks["shot_count"] = {"ok": False, "detail": f"Expected {min_shots}..{max_shots} shots, found {n_shots}"}

    # 2. Format aspect ratio
    expected_fmt = expected.get("format") or case.get("format", "9:16")
    doc_fmt = shots_doc.get("aspect_ratio", "")
    if doc_fmt == expected_fmt or all(s.get("aspect_ratio") == expected_fmt for s in shots if s.get("aspect_ratio")):
        checks["format"] = {"ok": True, "detail": f"Format {doc_fmt or expected_fmt} matches expected {expected_fmt}"}
    else:
        checks["format"] = {"ok": False, "detail": f"Format '{doc_fmt}' does not match expected '{expected_fmt}'"}

    # 3. Voice lines in project language/script
    lang = expected.get("language") or brief.get("language", "English")
    script = expected.get("script") or ("tamil" if lang.lower() == "tamil" else "latin")
    voice_lines = [s.get("voice_line") or "" for s in shots if s.get("voice_line")]
    full_voice = " ".join(voice_lines).strip()
    if not full_voice:
        checks["language_script"] = {"ok": False, "detail": "No voice lines present in shots"}
    elif script == "tamil" or lang.lower() == "tamil":
        ratio = lang_mod.script_ratio(full_voice, "Tamil")
        if ratio is not None and ratio > 0.2:
            checks["language_script"] = {"ok": True, "detail": f"Tamil script ratio {ratio:.1%} in voice lines"}
        else:
            checks["language_script"] = {"ok": False, "detail": f"Tamil script ratio too low: {ratio if ratio is not None else 0:.1%}"}
    elif script == "latin" or lang.lower() == "english":
        ratio = lang_mod.latin_ratio(full_voice)
        if ratio is not None and ratio > 0.8:
            checks["language_script"] = {"ok": True, "detail": f"Latin script ratio {ratio:.1%} in voice lines"}
        else:
            checks["language_script"] = {"ok": False, "detail": f"Latin script ratio too low: {ratio if ratio is not None else 0:.1%}"}
    else:
        checks["language_script"] = {"ok": True, "detail": f"Voice lines present ({len(full_voice)} chars)"}

    # 4. Valid model per catalog
    bad_models = []
    for s in shots:
        m = s.get("model")
        if not m or not is_valid_catalog_model(ws.catalog(), m):
            bad_models.append(f"{s.get('id')}:{m}")
    if bad_models:
        checks["model_validity"] = {"ok": False, "detail": f"Shots with invalid catalog models: {', '.join(bad_models)}"}
    else:
        checks["model_validity"] = {"ok": True, "detail": f"All {n_shots} shots have valid catalog models"}

    # 5. Documents validate against schemas
    schema_problems = []
    try:
        ShotsDoc.model_validate(shots_doc)
    except Exception as e:
        schema_problems.append(f"shots.json: {e}")
    if (p / "images.json").is_file():
        try:
            ImagesDoc.model_validate(ws._read(p, "images.json", {}))
        except Exception as e:
            schema_problems.append(f"images.json: {e}")
    if (p / "edit.json").is_file():
        try:
            EditDoc.model_validate(ws._read(p, "edit.json", {}))
        except Exception as e:
            schema_problems.append(f"edit.json: {e}")
    if schema_problems:
        checks["schema_validity"] = {"ok": False, "detail": "; ".join(schema_problems)[:300]}
    else:
        checks["schema_validity"] = {"ok": True, "detail": "All project documents validate against schemas"}

    # 6. Proposals only (no approvals or forbidden tools attempted/executed)
    budget = ws._read(p, "budget.json", {})
    approvals = ws._read(p, "approvals.json", [])
    forbidden = set(tool_registry.APPROVAL) | set(tool_registry.HUMAN_ONLY)

    all_steps = list(run_rec.get("steps", []))
    for res in run_rec.get("results", []):
        for run_id in res.get("runs", []):
            try:
                child = runtime.get_run(ws, project, run_id)
                all_steps.extend(child.get("steps", []))
            except Exception:
                pass

    bad_tool_attempt = next((s for s in all_steps if s.get("tool") in forbidden), None)
    if budget.get("approved"):
        checks["proposals_only"] = {"ok": False, "detail": "Budget was approved (expected proposals only)"}
    elif any(a.get("status") == "approved" for a in approvals):
        checks["proposals_only"] = {"ok": False, "detail": "Approved proposal found (expected proposals only)"}
    elif bad_tool_attempt:
        checks["proposals_only"] = {"ok": False, "detail": f"Forbidden tool attempted: {bad_tool_attempt.get('tool')}"}
    else:
        checks["proposals_only"] = {"ok": True, "detail": "Proposals only, no approvals or forbidden tools attempted/executed"}

    # 7. Paid batch total <= budget cap
    max_paid = float(expected.get("max_paid_total") or brief.get("budget_cap") or 999.0)
    proposals = list(run_rec.get("proposals", []))
    for res in run_rec.get("results", []):
        for run_id in res.get("runs", []):
            try:
                child = runtime.get_run(ws, project, run_id)
                proposals.extend(child.get("proposals", []))
            except Exception:
                pass
    proposed_total = round(sum(float(pr.get("price") or 0) for pr in proposals), 6)
    if proposed_total > max_paid:
        checks["budget_cap"] = {"ok": False, "detail": f"Paid total ${proposed_total:.3f} exceeds cap ${max_paid:.3f}"}
    else:
        checks["budget_cap"] = {"ok": True, "detail": f"Paid total ${proposed_total:.3f} <= cap ${max_paid:.3f}"}

    passed = all(c["ok"] for c in checks.values())
    score = sum(1 for c in checks.values() if c["ok"]) / len(checks) if checks else 0.0

    return {
        "case_id": case.get("id"),
        "case_name": case.get("name"),
        "format": doc_fmt or expected_fmt,
        "language": lang,
        "shot_count": n_shots,
        "checks": checks,
        "passed": passed,
        "score": round(score, 4),
        "llm_usd": float(run_rec.get("llm_usd") or 0.0),
    }


def run_eval_case(ws, case, model=None, allow_paid=False, llm=None):
    """Run ONE evaluation case through the crew runtime in a temp test project. Returns evaluation result."""
    # Paid model check
    if is_paid_chat_model(ws, model) and not allow_paid:
        spend = estimate_max_llm_spend(ws, [case], stage=case.get("stage", "write_storyboard"))
        raise ServiceError(f"Chat model '{model or 'configured'}' is a paid model. Max LLM spend estimated at ${spend:.2f}. Pass --allow-paid to proceed.")

    case_id = case.get("id", "case")
    pname = f"test-eval-{case_id}-{uuid.uuid4().hex[:6]}"
    ws.create_project(pname)
    pdir = ws.pdir(pname)
    # Ensure it is marked as a test pipeline sandbox
    (pdir / "sandbox.json").write_text(json.dumps({"enabled": True}), encoding="utf-8")

    try:
        # Populate brief
        brief = case.get("brief", {})
        if brief:
            ws.brief_put(pname, brief)

        stage = case.get("stage", "write_storyboard")
        # Run through the REAL crew runtime with checkpoints turned off for automated eval
        rec = stages.run_stages(ws, pname, [stage], autonomy="copilot", checkpoints={stage: False}, llm=llm)
        result = evaluate_project(ws, pname, case, rec)
        result["run_id"] = rec.get("id")
        return result
    finally:
        # Clean up temp test project directory
        try:
            shutil.rmtree(pdir)
        except OSError:
            pass


def save_report(ws, report):
    """Store report JSON under <workspace>/evals/."""
    evals_dir = ws.root / "evals"
    evals_dir.mkdir(parents=True, exist_ok=True)
    ts = int(report.get("timestamp") or time.time())
    path = evals_dir / f"crew_eval_{ts}.json"
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def format_table(report):
    """Format report into a human-readable terminal table."""
    lines = []
    ts_str = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(report.get("timestamp", time.time())))
    lines.append(f"Crew Evaluation Report ({ts_str})")
    model_name = report.get("model") or "default"
    summary = report.get("summary", {})
    lines.append(f"Model: {model_name} | Passed: {summary.get('passed', 0)}/{summary.get('total_cases', 0)} | Total LLM: ${summary.get('total_llm_usd', 0.0):.4f}")
    lines.append("")
    lines.append(f"{'Case ID':<24} {'Format':<8} {'Language':<10} {'Shots':<8} {'Score':<8} {'Status':<8}")
    lines.append("-" * 72)
    for c in report.get("results", []):
        status = "PASS" if c.get("passed") else "FAIL"
        score_str = f"{c.get('score', 0):.0%}"
        shots_str = str(c.get("shot_count", "-"))
        lines.append(f"{c.get('case_id', '-'):<24} {c.get('format', '-'):<8} {c.get('language', '-'):<10} {shots_str:<8} {score_str:<8} {status:<8}")
        if not c.get("passed"):
            for ch_name, ch in c.get("checks", {}).items():
                if not ch.get("ok"):
                    lines.append(f"  x [{ch_name}] {ch.get('detail')}")
    lines.append("-" * 72)
    return "\n".join(lines)


def run_eval(ws, cases=None, case_id=None, model=None, allow_paid=False, llm=None, out=None, cases_dir=None):
    """Run full evaluation suite, print table/JSON, and store report under <workspace>/evals/."""
    all_cases = cases or load_cases(cases_dir)
    if case_id:
        target_cases = [c for c in all_cases if c["id"] == case_id]
        if not target_cases:
            raise ServiceError(f"unknown eval case '{case_id}'")
    else:
        target_cases = all_cases

    if not target_cases:
        raise ServiceError("no eval cases found")

    # Safety: check paid chat model and show spend first
    if is_paid_chat_model(ws, model):
        spend = estimate_max_llm_spend(ws, target_cases)
        if not allow_paid:
            raise ServiceError(f"Chat model '{model or 'configured'}' is a paid model. Max LLM spend estimated at ${spend:.2f}. Pass --allow-paid to proceed.")
        if out:
            out(f"Running with paid chat model '{model or 'configured'}'. Max LLM spend estimated at ${spend:.2f}.")

    results = []
    total_llm = 0.0
    for case in target_cases:
        res = run_eval_case(ws, case, model=model, allow_paid=allow_paid, llm=llm)
        results.append(res)
        total_llm += res.get("llm_usd", 0.0)

    n_passed = sum(1 for r in results if r.get("passed"))
    report = {
        "timestamp": time.time(),
        "model": model or "default",
        "summary": {
            "total_cases": len(results),
            "passed": n_passed,
            "failed": len(results) - n_passed,
            "total_llm_usd": round(total_llm, 6),
        },
        "results": results,
    }

    report_path = save_report(ws, report)
    report["report_path"] = str(report_path)
    return report
