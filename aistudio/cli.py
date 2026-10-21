"""Human and Agent terminal interface for AI Studio.

Commands:
  python3 -m aistudio.cli serve                      Start the web UI
  python3 -m aistudio.cli projects [--json]          List projects with budget/spend
  python3 -m aistudio.cli overview <project> [--json] Project overview
  python3 -m aistudio.cli delete-project <p> [-y]    Move project to _trash
  python3 -m aistudio.cli pending <project> [--json] Proposals waiting for decision
  python3 -m aistudio.cli approve <project> <id> [-y] Approve ONE proposal
  python3 -m aistudio.cli run <project> <id> [-y]    Execute an approved proposal
  python3 -m aistudio.cli reject <project> <id> [-y] Reject a pending proposal
  python3 -m aistudio.cli approve-budget <p> [-y]    Approve budget estimate
  python3 -m aistudio.cli approve-shot <p> <s> [-y]  Approve video clip for shot
  python3 -m aistudio.cli discard <p> <rel> [-y]     Move clip/still to _discarded
  python3 -m aistudio.cli restore <p> <rel> [-y]     Restore discarded clip/still
  python3 -m aistudio.cli trash-list [--json]        List deleted projects in trash
  python3 -m aistudio.cli restore-trash <tid> [-y]   Restore project from trash
  python3 -m aistudio.cli convert-story <p> [--json] Parse Story.md -> shots.json
  python3 -m aistudio.cli verify <project> [--json]  Verification rules status
  python3 -m aistudio.cli progress <p> [--json]      Production checklist and queue
  python3 -m aistudio.cli plan <project> [--json]    Batch generation proposal plan
  python3 -m aistudio.cli export-project <p> [--json] Export project zip archive
  python3 -m aistudio.cli agent-setup [claude|agy]   Configure agent manifests
"""
import argparse
import json
import os
import sys
from pathlib import Path

from aistudio.service import REPO, ServiceError, Workspace


def _setup_agent(agent: str, repo: Path, out=print):
    """Generate configuration files for Claude Code or Antigravity CLI."""
    created = []
    if agent in ("claude", "all"):
        mcp_cfg = {
            "mcpServers": {
                "ai-studio": {
                    "command": sys.executable,
                    "args": ["-m", "aistudio.mcp_server"],
                    "env": {"AISTUDIO_HOME": str(repo)},
                }
            }
        }
        p = repo / ".mcp.json"
        p.write_text(json.dumps(mcp_cfg, indent=2) + "\n", encoding="utf-8")
        created.append(str(p))

    if agent in ("agy", "all"):
        skill_dir = repo / ".agents" / "skills" / "aistudio"
        skill_dir.mkdir(parents=True, exist_ok=True)
        skill_file = skill_dir / "SKILL.md"
        if not skill_file.exists():
            skill_file.write_text(
                "---\nname: aistudio\ndescription: Manage AI Studio commercial video production, shots, storyboard, and batch rendering.\n---\n"
                "# AI Studio Skill\nRun `python3 -m aistudio.cli projects --json` to list projects.\n",
                encoding="utf-8",
            )
            created.append(str(skill_file))

    for c in created:
        out(f"Configured: {c}")
    return {"created": created}


def main(argv=None, ask=input, out=print):
    ap = argparse.ArgumentParser(prog="aistudio", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--json", action="store_true", help="Output results as JSON")
    sp = ap.add_subparsers(dest="cmd", required=True)

    sp.add_parser("serve", help="Start web UI")

    p_proj = sp.add_parser("projects", help="List projects")
    p_proj.add_argument("--json", action="store_true")

    p_over = sp.add_parser("overview", help="Project overview")
    p_over.add_argument("project")
    p_over.add_argument("--json", action="store_true")

    p_del = sp.add_parser("delete-project", aliases=["trash-project"], help="Move a project to _trash")
    p_del.add_argument("project")
    p_del.add_argument("-y", "--yes", action="store_true", help="Bypass interactive prompt")

    p_pend = sp.add_parser("pending", help="Pending proposals")
    p_pend.add_argument("project")
    p_pend.add_argument("--json", action="store_true")

    p_app = sp.add_parser("approve", help="Approve proposal")
    p_app.add_argument("project")
    p_app.add_argument("id")
    p_app.add_argument("-y", "--yes", action="store_true", help="Bypass interactive prompt")

    p_run = sp.add_parser("run", help="Execute an approved proposal")
    p_run.add_argument("project")
    p_run.add_argument("id")
    p_run.add_argument("-y", "--yes", action="store_true", help="Bypass interactive prompt")
    p_run.add_argument("--override", action="store_true", help="Unsupported: gate overrides require the human web session")

    p_rej = sp.add_parser("reject", help="Reject a pending proposal")
    p_rej.add_argument("project")
    p_rej.add_argument("id")
    p_rej.add_argument("-y", "--yes", action="store_true", help="Bypass interactive prompt")

    p_bud = sp.add_parser("approve-budget", help="Approve budget")
    p_bud.add_argument("project")
    p_bud.add_argument("-y", "--yes", action="store_true", help="Bypass interactive prompt")

    p_shot = sp.add_parser("approve-shot", help="Approve a shot clip")
    p_shot.add_argument("project")
    p_shot.add_argument("shot_id")
    p_shot.add_argument("-y", "--yes", action="store_true", help="Bypass interactive prompt")

    p_disc = sp.add_parser("discard", help="Move clip or still to _discarded")
    p_disc.add_argument("project")
    p_disc.add_argument("rel")
    p_disc.add_argument("--reason", default="", help="Reason for discarding")
    p_disc.add_argument("-y", "--yes", action="store_true", help="Bypass interactive prompt")

    p_rst = sp.add_parser("restore", help="Restore discarded clip or still")
    p_rst.add_argument("project")
    p_rst.add_argument("rel")
    p_rst.add_argument("-y", "--yes", action="store_true", help="Bypass interactive prompt")

    p_trlist = sp.add_parser("trash-list", help="List projects in trash")
    p_trlist.add_argument("--json", action="store_true")

    p_trrst = sp.add_parser("restore-trash", help="Restore a project from trash")
    p_trrst.add_argument("tid")
    p_trrst.add_argument("--as-name", default=None, help="Restore with new project name")
    p_trrst.add_argument("-y", "--yes", action="store_true", help="Bypass interactive prompt")

    p_conv = sp.add_parser("convert-story", help="Convert Story.md to shots and images")
    p_conv.add_argument("project")
    p_conv.add_argument("--json", action="store_true")

    p_ver = sp.add_parser("verify", help="Check verification rules")
    p_ver.add_argument("project")
    p_ver.add_argument("--json", action="store_true")

    p_prog = sp.add_parser("progress", help="Production progress")
    p_prog.add_argument("project")
    p_prog.add_argument("--json", action="store_true")

    p_plan = sp.add_parser("plan", help="Batch generation proposal plan")
    p_plan.add_argument("project")
    p_plan.add_argument("--json", action="store_true")

    p_jobs = sp.add_parser("jobs", help="List jobs from the durable job ledger")
    p_jobs.add_argument("project", nargs="?", default="")
    p_jobs.add_argument("--state", default="")
    p_jobs.add_argument("--json", action="store_true")

    p_exp = sp.add_parser("export-project", help="Export project as zip")
    p_exp.add_argument("project")
    p_exp.add_argument("--include-discarded", action="store_true")
    p_exp.add_argument("--json", action="store_true")

    p_set = sp.add_parser("agent-setup", help="Configure agent manifests")
    p_set.add_argument("agent", choices=["claude", "agy", "all"], default="all", nargs="?")

    args = ap.parse_args(argv)
    home = Path(os.environ.get("AISTUDIO_HOME") or REPO)
    ws = Workspace(home)
    is_json = getattr(args, "json", False)

    try:
        if args.cmd == "serve":
            from server.app import main as serve
            return serve()

        if args.cmd == "projects":
            res = ws.list_projects()
            if is_json:
                out(json.dumps(res, indent=2))
            else:
                for p in res:
                    out(f"{p['name']:<24} shots {p['shots']:<3} spent ${p['spent']:<8} budget {'approved' if p['approved'] else 'none'}")

        elif args.cmd == "overview":
            res = ws.overview(args.project)
            if is_json:
                out(json.dumps(res, indent=2))
            else:
                out(f"Project: {res['name']} ({res['mode']} mode)")
                out(f"Shots: {len(res['shots'].get('shots', []))}, Images: {len(res['images'].get('images', []))}")
                out(f"Spent: ${res['costs']['total']:.3f}")

        elif args.cmd in ("delete-project", "trash-project"):
            if not getattr(args, "yes", False):
                out(f"Moving project '{args.project}' to _trash (restorable).")
                if ask("Type yes to confirm: ").strip().lower() != "yes":
                    return out("Not confirmed.")
            res = ws.delete_project(args.project, "yes")
            if is_json:
                out(json.dumps(res, indent=2))
            else:
                out(f"Project '{res.get('name', args.project)}' moved to trash: {res.get('trash')}")

        elif args.cmd == "jobs":
            from aistudio import jobs as jobsmod
            res = jobsmod.list_jobs(ws.root, args.project or None, args.state or None)
            if is_json:
                out(json.dumps(res, indent=2))
            else:
                for j in res:
                    out(f"{j['id']}  {j['project']:<20} {j['kind']:<8} {j['state']:<16} {j['target']}  {j['error']}".rstrip())

        elif args.cmd == "pending":
            proposals = ws.overview(args.project)["proposals"]
            pending = [p for p in proposals if p["status"] in ("pending", "approved")]
            if is_json:
                out(json.dumps(pending, indent=2))
            else:
                for p in pending:
                    out(f"{p['id']}  {p['status']:<9} {p['kind']:<7} {p['shot']:<8} ${p['price']:.3f}  {p['model']}\n    {(p.get('summary') or {}).get('prompt', '')[:160]}")

        elif args.cmd == "approve":
            if getattr(args, "yes", False):
                raise ServiceError("--yes cannot bypass human proposal approval; omit it for the interactive human prompt")
            p = ws.proposal_status(args.project, args.id)
            if not getattr(args, "yes", False):
                out(f"{p['kind']} {p['shot']} with {p['model']} for ${p['price']:.3f}\n  {(p.get('summary') or {}).get('prompt', '')[:300]}")
                if ask("Type yes to approve this exact request: ").strip().lower() != "yes":
                    return out("Not approved.")
            ws.approve_human(args.project, args.id)
            out("Approved. The agent (or the web UI) can now run it once.")

        elif args.cmd == "run":
            if getattr(args, "override", False):
                raise ServiceError("gate overrides require a human web session; CLI agents cannot override")
            p = ws.proposal_status(args.project, args.id)
            if not getattr(args, "yes", False):
                out(f"Execute {p['kind']} {p['shot']} with {p['model']} for ${p['price']:.3f}?")
                if ask("Type yes to execute: ").strip().lower() != "yes":
                    return out("Not confirmed.")
            res = ws.execute(args.project, args.id)
            if is_json:
                out(json.dumps(res, indent=2))
            else:
                out(f"Executed proposal {args.id}: {res.get('file', 'ok')}")

        elif args.cmd == "reject":
            if not getattr(args, "yes", False):
                if ask(f"Reject proposal {args.id}? Type yes to confirm: ").strip().lower() != "yes":
                    return out("Not confirmed.")
            res = ws.reject(args.project, args.id) or {"ok": True, "rejected": args.id}
            if is_json:
                out(json.dumps(res, indent=2))
            else:
                out(f"Proposal {args.id} rejected.")

        elif args.cmd == "approve-budget":
            if getattr(args, "yes", False):
                raise ServiceError("--yes cannot bypass human budget approval; omit it for the interactive human prompt")
            b = ws.overview(args.project)["budget"]
            if not getattr(args, "yes", False):
                out(f"Estimate ${b.get('estimate')} with stop-loss ${b.get('stop_loss')}")
                if ask("Type yes to approve this budget: ").strip().lower() != "yes":
                    return out("Not approved.")
            ws.approve_budget(args.project)
            out("Budget approved.")

        elif args.cmd == "approve-shot":
            if getattr(args, "yes", False):
                raise ServiceError("--yes cannot bypass human clip approval; omit it for the interactive human prompt")
            if not getattr(args, "yes", False):
                if ask(f"Approve video clip for shot {args.shot_id}? Type yes to confirm: ").strip().lower() != "yes":
                    return out("Not confirmed.")
            res = ws.approve_shot(args.project, args.shot_id) or {"ok": True, "approved_shot": args.shot_id}
            if is_json:
                out(json.dumps(res, indent=2))
            else:
                out(f"Shot {args.shot_id} approved.")

        elif args.cmd == "discard":
            if not getattr(args, "yes", False):
                if ask(f"Discard {args.rel}? Type yes to confirm: ").strip().lower() != "yes":
                    return out("Not confirmed.")
            res = ws.discard(args.project, args.rel, reason=args.reason)
            if is_json:
                out(json.dumps(res, indent=2))
            else:
                out(f"Discarded {args.rel}: {res}")

        elif args.cmd == "restore":
            if not getattr(args, "yes", False):
                if ask(f"Restore {args.rel}? Type yes to confirm: ").strip().lower() != "yes":
                    return out("Not confirmed.")
            res = ws.restore(args.project, args.rel)
            if is_json:
                out(json.dumps({"file": str(res)}, indent=2))
            else:
                out(f"Restored: {res}")

        elif args.cmd == "trash-list":
            res = ws.trash_list()
            if is_json:
                out(json.dumps(res, indent=2))
            else:
                for t in res:
                    out(f"{t['id']:<40} original: {t.get('name', 'unknown')}")

        elif args.cmd == "restore-trash":
            if not getattr(args, "yes", False):
                if ask(f"Restore trash item {args.tid}? Type yes to confirm: ").strip().lower() != "yes":
                    return out("Not confirmed.")
            res = ws.trash_restore(args.tid, as_name=args.as_name)
            if is_json:
                out(json.dumps(res, indent=2))
            else:
                out(f"Restored project: {res['name']}")

        elif args.cmd == "convert-story":
            res = ws.convert_story(args.project)
            if is_json:
                out(json.dumps(res, indent=2))
            else:
                shots = res.get("shots", {}).get("shots", [])
                imgs = res.get("images", {}).get("images", [])
                out(f"Converted Story.md: {len(shots)} shots, {len(imgs)} images created.")

        elif args.cmd == "verify":
            res = ws.verify_status(args.project)
            if is_json:
                out(json.dumps(res, indent=2))
            else:
                for scope, st in res.items():
                    out(f"[{scope.upper()}] status: {st['status']}, findings: {len(st.get('findings', []))}")

        elif args.cmd == "progress":
            res = ws.production_progress(args.project)
            if is_json:
                out(json.dumps(res, indent=2))
            else:
                out(f"Next: {res.get('next', {}).get('label', 'None')}")
                for g in res.get("groups", []):
                    out(f"  {g['label']}: {g['done']}/{g['total']}")

        elif args.cmd == "plan":
            res = ws.generate_all_plan(args.project)
            if is_json:
                out(json.dumps(res, indent=2))
            else:
                out(f"Batch Plan: {len(res['items'])} items to generate, Total: ${res['total']:.3f}")

        elif args.cmd == "export-project":
            res = str(ws.export_project(args.project, include_discarded=args.include_discarded))
            if is_json:
                out(json.dumps({"path": res}, indent=2))
            else:
                out(f"Exported project archive: {res}")

        elif args.cmd == "agent-setup":
            res = _setup_agent(args.agent, home, out=out)
            if is_json:
                out(json.dumps(res, indent=2))

    except ServiceError as e:
        if is_json:
            out(json.dumps({"error": str(e)}))
        else:
            out(f"error: {e}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
