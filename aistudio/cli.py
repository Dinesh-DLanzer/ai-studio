"""Human-facing terminal commands. Approvals made here are HUMAN approvals (an agent must not call this).

  python3 -m aistudio.cli serve                      start the web UI (prints the session token link)
  python3 -m aistudio.cli projects                   list projects
  python3 -m aistudio.cli pending <project>          proposals waiting for a decision
  python3 -m aistudio.cli approve <project> <id>     approve ONE proposal after showing its price (asks you to type yes)
  python3 -m aistudio.cli approve-budget <project>   approve the current estimate
"""
import argparse
import os
import sys

from aistudio.service import REPO, ServiceError, Workspace


def main(argv=None, ask=input, out=print):
    ap = argparse.ArgumentParser(prog="aistudio", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)
    sp.add_parser("serve"); sp.add_parser("projects")
    for n in ("pending", "approve-budget"):
        sp.add_parser(n).add_argument("project")
    a = sp.add_parser("approve"); a.add_argument("project"); a.add_argument("id")
    args = ap.parse_args(argv)
    home = os.environ.get("AISTUDIO_HOME") or REPO
    ws = Workspace(home)
    try:
        if args.cmd == "serve":
            from server.app import main as serve
            return serve()
        if args.cmd == "projects":
            for p in ws.list_projects():
                out(f"{p['name']:<24} shots {p['shots']:<3} spent ${p['spent']:<8} budget {'approved' if p['approved'] else 'none'}")
        elif args.cmd == "pending":
            for p in ws.overview(args.project)["proposals"]:
                if p["status"] in ("pending", "approved"):
                    out(f"{p['id']}  {p['status']:<9} {p['kind']:<7} {p['shot']:<8} ${p['price']:.3f}  {p['model']}\n    {(p.get('summary') or {}).get('prompt', '')[:160]}")
        elif args.cmd == "approve":
            p = ws.proposal_status(args.project, args.id)
            out(f"{p['kind']} {p['shot']} with {p['model']} for ${p['price']:.3f}\n  {(p.get('summary') or {}).get('prompt', '')[:300]}")
            if ask("Type yes to approve this exact request: ").strip().lower() != "yes":
                return out("Not approved.")
            ws.approve_human(args.project, args.id)
            out("Approved. The agent (or the web UI) can now run it once.")
        elif args.cmd == "approve-budget":
            b = ws.overview(args.project)["budget"]
            out(f"Estimate ${b.get('estimate')} with stop-loss ${b.get('stop_loss')}")
            if ask("Type yes to approve this budget: ").strip().lower() != "yes":
                return out("Not approved.")
            ws.approve_budget(args.project)
            out("Budget approved.")
    except ServiceError as e:
        out(f"error: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
