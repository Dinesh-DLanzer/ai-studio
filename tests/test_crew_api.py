import tests._hermetic as HERM  # noqa: F401
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

try:
    from fastapi.testclient import TestClient
    from server.app import create_app
    HAVE = True
except Exception:
    HAVE = False
from aistudio import cli, jobs, mcp_server
from aistudio.crew import agents, runtime
from aistudio.service import Workspace
from server import api_docs
from tests.test_crew_runtime import DONE, Script, act
from tests.test_spend_integrity import ANSWERS

FIX = Path(__file__).parent / "fixtures" / "agents"
WRITE = [act("write_doc", name="demo", doc="Story.md", text="# By the crew\n"), DONE]


def scripted(replies):
    llm = Script(replies)
    return patch.object(runtime, "default_llm", lambda ws, project: llm)


class Base(unittest.TestCase):
    def setUp(self):
        HERM.all_test(self)
        self.root = tempfile.mkdtemp()
        ws = Workspace(self.root)
        ws.create_project("demo")
        for t in ["hello"] + ANSWERS + ["skip"]:
            ws.chat_send("demo", t)
        self.story = (ws.pdir("demo") / "Story.md").read_bytes()
        p = patch.object(agents, "DIRS", [FIX])
        p.start()
        self.addCleanup(p.stop)


@unittest.skipUnless(HAVE, "needs the venv with fastapi + httpx")
class CrewServerTests(Base):
    def setUp(self):
        super().setUp()
        self.c = TestClient(create_app(self.root, token="tok", static_dir="/nonexistent"))
        self.S = {"x-aistudio-token": "tok"}
        key = self.c.post("/api/keys", json={"name": "agent"}, headers=self.S).json()["key"]
        self.A = {"x-aistudio-token": key}
        self.base = "/api/projects/demo/crew/runs"

    def wait(self, jid):
        for _ in range(200):
            j = self.c.get(f"/api/jobs/{jid}", headers=self.S).json()
            if j["status"] != "running":
                return j
            time.sleep(0.05)
        self.fail("run did not finish")

    def start(self, **kw):
        r = self.c.post(self.base, json={"agent": "echo-writer", "task": "write it", **kw}, headers=self.S)
        self.assertEqual(r.status_code, 200, r.text)
        self.wait(r.json()["job"])
        return r.json()["run"]

    def test_start_get_list_undo(self):
        with scripted(WRITE):
            rid = self.start()
        run = self.c.get(f"{self.base}/{rid}", headers=self.S).json()
        self.assertEqual((run["status"], [c["doc"] for c in run["changes"]]), ("done", ["Story.md"]))
        self.assertEqual(self.c.get(self.base, headers=self.S).json()["runs"][0]["id"], rid)
        self.assertEqual(jobs.get(self.root, rid)["kind"], "crew_run")
        self.assertEqual(jobs.get(self.root, rid)["state"], "completed")
        self.assertEqual(self.c.post(f"{self.base}/{rid}/undo", headers=self.S).json()["restored"], ["Story.md"])
        self.assertEqual((Path(self.root) / "projects" / "demo" / "Story.md").read_bytes(), self.story)

    def test_assist_run_applies_nothing(self):
        with scripted(WRITE):
            rid = self.start(autonomy="assist")
        self.assertEqual((Path(self.root) / "projects" / "demo" / "Story.md").read_bytes(), self.story)
        self.assertEqual(self.c.get(f"{self.base}/{rid}", headers=self.S).json()["suggested_changes"][0]["applied"], False)

    def test_bad_requests(self):
        for body in ({"agent": "nope", "task": "x"}, {"agent": "echo-writer", "task": ""}, {"agent": "echo-writer", "task": "x", "autonomy": "autopilot"}):
            self.assertEqual(self.c.post(self.base, json=body, headers=self.S).status_code, 400, body)

    def test_api_keys_can_read_but_never_start_undo_or_stop(self):
        with scripted(WRITE):
            rid = self.start()
        self.assertEqual(self.c.post(self.base, json={"agent": "echo-writer", "task": "x"}, headers=self.A).status_code, 403)
        self.assertEqual(self.c.post(f"{self.base}/{rid}/undo", headers=self.A).status_code, 403)
        self.assertEqual(self.c.post(f"{self.base}/{rid}/stop", headers=self.A).status_code, 403)
        self.assertEqual(self.c.get(self.base, headers=self.A).status_code, 200)
        self.assertEqual(self.c.get(f"{self.base}/{rid}", headers=self.A).status_code, 200)
        self.assertEqual((Path(self.root) / "projects" / "demo" / "Story.md").read_text(), "# By the crew\n")      # nothing was undone

    def test_stop_cancels_a_run(self):
        with scripted([act("get_brief", name="demo")] * 6):
            r = self.c.post(self.base, json={"agent": "echo-writer", "task": "x"}, headers=self.S)
            jid = r.json()["job"]
            self.c.post(f"{self.base}/{jid}/stop", headers=self.S)
            self.wait(jid)
        self.assertIn(jobs.get(self.root, jid)["state"], ("cancelled", "completed"))
        self.assertEqual(self.c.post(f"{self.base}/nope123/stop", headers=self.S).status_code, 404)

    def test_docs_mark_the_routes(self):
        self.assertEqual(api_docs.undocumented(self.c.app), [])
        for m, path, allowed in (("POST", "/api/projects/{name}/crew/runs", False), ("POST", "/api/projects/{name}/crew/runs/{rid}/undo", False),
                                 ("POST", "/api/projects/{name}/crew/runs/{rid}/stop", False), ("GET", "/api/projects/{name}/crew/runs", True)):
            self.assertEqual(api_docs.agent_allowed(m, path), allowed, path)


class CrewCliMcpTests(Base):
    def run_cli(self, argv):
        lines = []
        os.environ["AISTUDIO_HOME"] = self.root
        self.addCleanup(os.environ.pop, "AISTUDIO_HOME", None)
        return cli.main(argv, ask=lambda q: "no", out=lines.append), lines

    def test_cli_run_status_undo_and_mcp_read(self):
        with scripted(WRITE):
            code, lines = self.run_cli(["crew", "run", "demo", "--agent", "echo-writer", "--task", "write it", "--json"])
        rec = json.loads("".join(lines))
        self.assertEqual((code, rec["status"]), (0, "done"))
        ws = Workspace(self.root)
        self.assertEqual(jobs.get(ws.root, rec["id"])["state"], "completed")
        code, lines = self.run_cli(["crew", "status", "demo", "--json"])
        self.assertEqual(json.loads("".join(lines))["runs"][0]["id"], rec["id"])
        out = mcp_server.TOOLS["get_crew_run"][2](ws, {"name": "demo", "id": rec["id"]})
        self.assertEqual(out["status"], "done")
        self.assertEqual(mcp_server.TOOLS["list_crew_runs"][2](ws, {"name": "demo"})["runs"][0]["id"], rec["id"])
        for forbidden in ("start_crew_run", "undo_crew_run", "stop_crew_run"):
            self.assertNotIn(forbidden, mcp_server.TOOLS)
        code, lines = self.run_cli(["crew", "undo", "demo", rec["id"], "--json"])
        self.assertEqual(json.loads("".join(lines))["restored"], ["Story.md"])
        self.assertEqual((ws.pdir("demo") / "Story.md").read_bytes(), self.story)

    def test_cli_unknown_agent_is_a_clean_error(self):
        code, lines = self.run_cli(["crew", "run", "demo", "--agent", "nobody", "--task", "x"])
        self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()
