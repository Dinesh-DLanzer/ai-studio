import tests._hermetic as HERM  # noqa: F401
import json
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
from aistudio import approvals, costlog
from aistudio.crew import agents, runtime
from aistudio.service import Workspace
from server import api_docs
from tests.test_crew_runtime import DONE, Script, act
from tests.test_spend_integrity import ANSWERS


@unittest.skipUnless(HAVE, "needs the venv with fastapi + httpx")
class StageApiTests(unittest.TestCase):
    def setUp(self):
        HERM.all_test(self)
        self.root = tempfile.mkdtemp()
        ws = Workspace(self.root)
        ws.create_project("demo")
        for t in ["hello"] + ANSWERS + ["skip"]:
            ws.chat_send("demo", t)
        self.p = ws.pdir("demo")
        self.c = TestClient(create_app(self.root, token="tok", static_dir="/nonexistent"))
        self.S = {"x-aistudio-token": "tok"}
        self.A = {"x-aistudio-token": self.c.post("/api/keys", json={"name": "agent"}, headers=self.S).json()["key"]}
        self.base = "/api/projects/demo/crew"

    def wait(self, jid):
        for _ in range(200):
            j = self.c.get(f"/api/jobs/{jid}", headers=self.S).json()
            if j["status"] != "running":
                return j
            time.sleep(0.05)
        self.fail("job did not finish")

    def script(self, replies):
        llm = Script(replies)
        p = patch.object(runtime, "default_llm", lambda ws, project: llm)
        p.start()
        self.addCleanup(p.stop)

    def plan(self, stages="write_storyboard"):
        return self.c.get(f"{self.base}/plan?stages={stages}", headers=self.S).json()

    def start(self, stage="write_storyboard", **kw):
        r = self.c.post(f"{self.base}/stages/{stage}/run", json={"plan_hash": self.plan(stage)["plan_hash"], **kw}, headers=self.S)
        self.assertEqual(r.status_code, 200, r.text)
        self.wait(r.json()["job"])
        return r.json()["run"]

    def getrun(self, rid):
        return self.c.get(f"{self.base}/runs/{rid}", headers=self.S).json()

    def test_plan_and_every_new_human_route_refuse_api_keys(self):
        self.script([])
        rid = self.start()
        calls = [("GET", f"{self.base}/plan"), ("POST", f"{self.base}/plan"), ("POST", f"{self.base}/stages/qa/run"),
                 ("POST", f"{self.base}/runs/{rid}/continue"), ("PUT", "/api/crew/agents/writer")]
        for m, url in calls:
            r = self.c.request(m, url, json={"plan_hash": "x", "decision": "approve_continue"}, headers=self.A)
            self.assertEqual(r.status_code, 403, (m, url))
        for m, path in (("GET", "/api/projects/{name}/crew/plan"), ("POST", "/api/projects/{name}/crew/plan"), ("POST", "/api/projects/{name}/crew/stages/{stage}/run"),
                        ("POST", "/api/projects/{name}/crew/runs/{rid}/continue"), ("PUT", "/api/crew/agents/{agent_id}")):
            self.assertFalse(api_docs.agent_allowed(m, path), path)
        self.assertEqual(api_docs.undocumented(self.c.app), [])
        self.assertEqual(self.getrun(rid)["status"], "awaiting_checkpoint")      # nothing was continued
        self.assertEqual(self.c.get("/api/crew/agents", headers=self.A).status_code, 403)

    def test_plan_endpoint_shows_costs_and_creates_nothing(self):
        self.c.post("/api/projects/demo/estimate", json={"failure": 0.2}, headers=self.S)
        self.c.post("/api/projects/demo/budget/approve", headers=self.S)
        plan = self.c.post(f"{self.base}/plan", json={"stages": "make_video", "checkpoints": {"qa": True}}, headers=self.S).json()
        self.assertEqual(plan["paid_total"], 0.78)
        self.assertTrue(next(s for s in plan["stages"] if s["stage"] == "qa")["checkpoint"])
        self.assertEqual(self.c.get(f"{self.base}/plan?stages=nonsense", headers=self.S).status_code, 400)
        self.assertEqual(approvals._load(self.p), [])

    def test_start_needs_the_reviewed_plan_and_the_prerequisites(self):
        url = f"{self.base}/stages/cast_and_design/run"
        self.assertEqual(self.c.post(url, json={}, headers=self.S).status_code, 400)
        self.assertEqual(self.c.post(url, json={"plan_hash": "stale"}, headers=self.S).status_code, 409)
        r = self.c.post(url, json={"plan_hash": self.plan("cast_and_design")["plan_hash"]}, headers=self.S)
        self.assertEqual(r.status_code, 400)
        self.assertIn("budget", r.json()["detail"])
        self.assertEqual(runtime.list_runs(Workspace(self.root), "demo"), [])

    def test_checkpoint_continue_and_stop_over_http(self):
        self.script([])
        rid = self.start()
        run = self.getrun(rid)
        self.assertEqual((run["status"], run["results"][0]["card"]["options"][2]["id"]), ("awaiting_checkpoint", "stop"))
        cont = f"{self.base}/runs/{rid}/continue"
        self.assertEqual(self.c.post(cont, json={"decision": "approve_the_budget"}, headers=self.S).status_code, 400)
        r = self.c.post(cont, json={"decision": "approve_continue", "note": "looks right"}, headers=self.S)
        self.assertEqual(r.status_code, 200, r.text)
        self.wait(r.json()["job"])
        run = self.getrun(rid)
        self.assertEqual((run["status"], run["decisions"][0]["note"]), ("done", "looks right"))
        self.assertEqual(self.c.post(cont, json={"decision": "stop"}, headers=self.S).status_code, 400)       # not waiting any more
        self.assertEqual(costlog.read_log(self.p), [])

    def test_stop_decision_is_recorded(self):
        self.script([])
        rid = self.start()
        r = self.c.post(f"{self.base}/runs/{rid}/continue", json={"decision": "stop"}, headers=self.S)
        self.assertEqual(r.json()["status"], "stopped")
        self.assertEqual(self.getrun(rid)["decisions"][0]["decision"], "stop")

    def test_agents_list_and_safe_overrides(self):
        got = self.c.get("/api/crew/agents", headers=self.S).json()
        self.assertEqual({a["id"] for a in got["agents"]}, {"producer", "writer", "director", "scene-designer", "image-artist", "video-director", "editor", "qa",
                                                              "cinematographer", "casting-art-director", "sound-designer", "delivery"})
        self.assertEqual(got["hard_limits"], agents.HARD)
        tools = next(a for a in got["agents"] if a["id"] == "writer")["tools"]
        put = lambda body, aid="writer": self.c.put(f"/api/crew/agents/{aid}", json=body, headers=self.S)
        r = put({"prompt": "Write very short stories.", "limits": {"max_steps": 5}})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual((r.json()["prompt"], r.json()["limits"]["max_steps"], r.json()["tools"]), ("Write very short stories.", 5, tools))
        self.assertEqual(agents.load("writer", Workspace(self.root).settings_dir)["limits"]["max_steps"], 5)
        again = next(a for a in self.c.get("/api/crew/agents", headers=self.S).json()["agents"] if a["id"] == "writer")
        self.assertEqual(again["overridden"], ["limits", "prompt"])
        for bad in ({"tools": ["approve_budget"]}, {"limits": {"max_steps": 51}}, {"limits": {"max_llm_usd": 99}}, {"limits": {"tools": 1}}, {"limits": [1]},
                    {"prompt": ""}, {"engine": "codex"}, {"prompt": "x" * 13000}, ["x"]):
            self.assertEqual(put(bad).status_code, 400, bad)
        self.assertEqual(put({}, "nobody").status_code, 400)
        self.assertEqual(put({}, "../writer").status_code in (400, 404), True)
        self.assertEqual(agents.load("writer", Workspace(self.root).settings_dir)["tools"], tools)
        self.assertEqual(put({}).status_code, 200)       # reset
        self.assertNotEqual(agents.load("writer", Workspace(self.root).settings_dir)["prompt"], "Write very short stories.")

    def test_at_agent_message_starts_a_free_copilot_run(self):
        self.script([act("write_doc", name="demo", doc="Story.md", text="# Emotional\n"), DONE])
        r = self.c.post("/api/projects/demo/chat", json={"text": "@writer make shot 3 more emotional"}, headers=self.S)
        self.assertEqual(r.status_code, 200, r.text)
        out = r.json()
        self.assertEqual(out["routed_to"], "writer")
        self.wait(out["job"])
        run = self.getrun(out["run"])
        self.assertEqual((run["agent"]["id"], run["autonomy"], run["task"]), ("writer", "copilot", "make shot 3 more emotional"))
        self.assertEqual(costlog.read_log(self.p), [])
        self.assertEqual(self.c.post("/api/projects/demo/chat", json={"text": "@nobody hi"}, headers=self.S).status_code, 400)
        self.assertEqual(self.c.post("/api/projects/demo/chat", json={"text": "@writer hi"}, headers=self.A).status_code, 403)
        self.assertNotIn("routed_to", self.c.post("/api/projects/demo/chat", json={"text": "hello there"}, headers=self.S).json())


if __name__ == "__main__":
    unittest.main()
