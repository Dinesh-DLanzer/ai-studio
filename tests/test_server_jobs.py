import tests._hermetic as HERM  # noqa: F401
import os
import tempfile
import time
import unittest
from unittest.mock import patch

try:
    from fastapi.testclient import TestClient
    from server.app import create_app
    HAVE = True
except Exception:
    HAVE = False
from aistudio import jobs
from tests.test_spend_integrity import ANSWERS
from tests.test_story_convert import MD


@unittest.skipUnless(HAVE, "needs the venv with fastapi + httpx")
class TestServerJobs(unittest.TestCase):
    def setUp(self):
        HERM.all_test(self)
        self.root = tempfile.mkdtemp()
        self.start()
        self.c.post("/api/projects", json={"name": "demo", "test_pipeline": True}, headers=self.S)
        self.c.put("/api/projects/demo/docs/Story.md", json={"text": MD}, headers=self.S)
        self.c.post("/api/projects/demo/story/convert", headers=self.S)
        self.c.post("/api/projects/demo/estimate", json={"failure": 0.2}, headers=self.S)
        self.c.post("/api/projects/demo/budget/approve", headers=self.S)

    def start(self):
        self.app = create_app(self.root, token="tok", static_dir="/nonexistent")
        self.c = TestClient(self.app)
        self.S = {"x-aistudio-token": "tok"}
        key = self.c.post("/api/keys", json={"name": "agent"}, headers=self.S).json()["key"]
        self.A = {"x-aistudio-token": key}

    def wait_job(self, jid):
        for _ in range(100):
            r = self.c.get(f"/api/jobs/{jid}", headers=self.S).json()
            if r["status"] != "running":
                return r
            time.sleep(0.05)
        self.fail("job did not finish")

    def proposal(self, approve):
        prop = self.c.post("/api/projects/demo/proposals", json={"kind": "image", "target": "s01"}, headers=self.S).json()
        if approve:
            self.c.post(f"/api/projects/demo/proposals/{prop['id']}/approve", json={"code": prop["code"]}, headers=self.S)
        return prop["id"]

    def test_approved_execute_is_a_ledger_job(self):
        jid = self.c.post(f"/api/projects/demo/proposals/{self.proposal(True)}/execute", headers=self.S).json()["job"]
        r = self.wait_job(jid)
        self.assertEqual((r["status"], r["state"]), ("done", "completed"))
        rows = self.c.get("/api/jobs?project=demo", headers=self.S).json()["jobs"]
        self.assertEqual([(j["id"], j["state"], j["kind"], j["actor"], j["tenant_id"]) for j in rows], [(jid, "completed", "execute", "local", "local")])
        self.assertEqual(self.c.get("/api/jobs?project=other", headers=self.A).json()["jobs"], [])
        self.assertEqual(self.c.get("/api/jobs/nope", headers=self.S).status_code, 404)

    def test_no_job_executes_an_unapproved_proposal(self):
        pid = self.proposal(False)
        jid = self.c.post(f"/api/projects/demo/proposals/{pid}/execute", headers=self.S).json()["job"]
        r = self.wait_job(jid)
        self.assertEqual((r["status"], r["state"]), ("error", "failed"))
        self.assertFalse((self.app.state.ws.pdir("demo") / "stills" / "s01.png").exists())
        self.assertEqual(self.c.get("/api/projects/demo", headers=self.S).json()["costs"]["total"], 0)

    def test_api_key_cannot_cancel_but_human_can(self):
        job = jobs.enqueue(self.root, "demo", "execute", proposal_id="x")      # queued; no worker takes it
        self.assertEqual(self.c.post(f"/api/jobs/{job['id']}/cancel", headers=self.A).status_code, 403)
        self.assertEqual(jobs.get(self.root, job["id"])["state"], "queued")
        r = self.c.post(f"/api/jobs/{job['id']}/cancel", headers=self.S)
        self.assertEqual((r.status_code, r.json()["state"]), (200, "cancelled"))
        self.assertEqual(self.c.post("/api/jobs/nope/cancel", headers=self.S).status_code, 404)
        self.assertEqual(self.c.get("/api/jobs?project=demo", headers=self.A).status_code, 200)    # reading is allowed to agents

    def test_restart_marks_running_paid_job_needs_sync(self):
        job = jobs.enqueue(self.root, "demo", "execute", proposal_id="x", state="running")
        self.start()    # a restarted server on the same workspace
        r = self.c.get(f"/api/jobs/{job['id']}", headers=self.S).json()
        self.assertEqual((r["status"], r["state"]), ("error", "needs_sync"))
        self.assertIn("billed", r["error"])

    def test_batch_is_parent_job_with_child_jobs(self):
        c, S = self.c, self.S
        c.post("/api/projects", json={"name": "b", "test_pipeline": True}, headers=S)
        for text in ["hello"] + ANSWERS + ["skip"]:
            c.post("/api/projects/b/chat", json={"text": text}, headers=S)
        c.post("/api/projects/b/estimate", json={"failure": 0.2}, headers=S)
        c.post("/api/projects/b/budget/approve", headers=S)
        batch = c.post("/api/projects/b/batches", headers=S).json()
        base = f"/api/projects/b/batches/{batch['id']}"
        c.post(f"{base}/approve", json={"batch_hash": batch["batch_hash"]}, headers=S)
        r = self.wait_job(c.post(f"{base}/run", headers=S).json()["job"])
        self.assertEqual(r["status"], "done", r)
        rows = c.get("/api/jobs?project=b", headers=S).json()["jobs"]
        parent = [j for j in rows if j["kind"] == "batch"][0]
        kids = [j for j in rows if j["batch_id"] == parent["id"]]
        self.assertEqual(len(kids), len(batch["items"]))
        self.assertTrue(all(k["state"] == "completed" and k["proposal_id"] for k in kids))

    def test_legacy_escape_hatch_keeps_old_behaviour(self):
        with patch.dict(os.environ, {"AISTUDIO_LEGACY_JOBS": "1"}):
            self.start()
        jid = self.c.post(f"/api/projects/demo/proposals/{self.proposal(True)}/execute", headers=self.S).json()["job"]
        self.assertEqual(self.wait_job(jid)["status"], "done")
        self.assertEqual(jobs.list_jobs(self.root), [])

    def test_sse_stream_helper_reads_the_ledger(self):
        from aistudio import activity
        job = jobs.enqueue(self.root, "demo", "export", state="running")
        self.assertEqual([e["id"] for e in activity.job_events(self.root, "demo")], [job["id"]])


if __name__ == "__main__":
    unittest.main()
