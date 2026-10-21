import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from aistudio import project_lock


class LockBackendTests(unittest.TestCase):
    def test_injected_backend_is_used_and_released(self):
        calls = []
        backend = (lambda fh: calls.append("acquire"), lambda fh: calls.append("release"))
        with tempfile.TemporaryDirectory() as d, patch.object(project_lock, "_backend", return_value=backend):
            with project_lock.lock(Path(d)):
                self.assertEqual(calls, ["acquire"])
            self.assertEqual(calls, ["acquire", "release"])

    def test_no_backend_refuses(self):
        with tempfile.TemporaryDirectory() as d, patch.object(project_lock, "_backend", return_value=None):
            with self.assertRaises(RuntimeError):
                with project_lock.lock(Path(d)):
                    self.fail("must not run unlocked")

    def test_acquire_failure_refuses(self):
        def boom(fh):
            raise OSError("nope")
        with tempfile.TemporaryDirectory() as d, patch.object(project_lock, "_backend", return_value=(boom, lambda fh: None)):
            with self.assertRaises(RuntimeError):
                with project_lock.lock(Path(d)):
                    self.fail("must not run unlocked")

    def test_windows_fallback_uses_msvcrt(self):
        fake = types.SimpleNamespace(LK_LOCK=1, LK_UNLCK=0, calls=[])
        fake.locking = lambda fd, mode, n: fake.calls.append(mode)
        with patch.dict(sys.modules, {"fcntl": None, "msvcrt": fake}):
            acquire, release = project_lock._backend()
            with tempfile.TemporaryFile("a+") as fh:
                acquire(fh)
                release(fh)
        self.assertEqual(fake.calls, [1, 0])


# ---- multi-process stop-loss -------------------------------------------------
import json
import multiprocessing

import tests._hermetic as HERM  # noqa: E402,F401
from aistudio import costlog  # noqa: E402
from aistudio.service import ServiceError, Workspace  # noqa: E402
from tests.test_story_convert import MD  # noqa: E402


def _worker(root, pid, barrier, out):
    try:
        ws = Workspace(root)
        barrier.wait(30)
        ws.execute("demo", pid)
        out.put("ok")
    except ServiceError as error:
        out.put(f"refused: {error}")
    except BaseException as error:
        out.put(f"crash: {error!r}")


def make_project(case):
    HERM.all_test(case)
    tmp = tempfile.TemporaryDirectory()
    case.addCleanup(tmp.cleanup)
    ws = Workspace(tmp.name)
    ws.create_project("demo", test_pipeline=True)
    ws.put_text("demo", "Story.md", MD)
    ws.convert_story("demo")
    p = ws.pdir("demo")
    doc = json.loads((p / "images.json").read_text())
    if len(doc["images"]) < 2:  # the sample story has one still; add a second independent one
        doc["images"].append({**doc["images"][0], "id": "s02", "out": doc["images"][0]["out"].replace("s01", "s02")})
        (p / "images.json").write_text(json.dumps(doc))
    ws.estimate("demo")
    ws.approve_budget("demo")
    return ws, p, tmp.name


class MultiProcessStopLossTests(unittest.TestCase):
    def test_two_processes_cannot_both_pass_a_one_clip_stop_loss(self):
        ws, p, root = make_project(self)
        b = json.loads((p / "budget.json").read_text())
        b["stop_loss"] = 0.05  # one 0.036 image fits, two do not
        (p / "budget.json").write_text(json.dumps(b))
        targets = [i["id"] for i in json.loads((p / "images.json").read_text())["images"] if not (p / i["out"]).exists()][:2]
        pids = []
        for t in targets:
            prop = ws.propose("demo", "image", t)
            ws.approve_human("demo", prop["id"])
            pids.append(prop["id"])
        ctx = multiprocessing.get_context("spawn")
        barrier, out = ctx.Barrier(2), ctx.Queue()
        procs = [ctx.Process(target=_worker, args=(root, pid, barrier, out)) for pid in pids]
        for pr in procs:
            pr.start()
        results = []
        for _ in procs:
            try:
                results.append(out.get(timeout=60))
            except Exception as error:
                results.append(f"no result: {error!r}")
        for pr in procs:
            pr.join(30)
        self.assertEqual(sorted(r[:2] for r in results), ["ok", "re"], results)
        self.assertTrue(any("stop-loss" in r for r in results), results)
        rows = costlog.read_log(p)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["result"], "completed")


class BudgetDiffTests(unittest.TestCase):
    def setUp(self):
        self.ws, self.p, _ = make_project(self)

    def edit_shot(self, **fields):
        doc = json.loads((self.p / "shots.json").read_text())
        doc["shots"][0].update(fields)
        (self.p / "shots.json").write_text(json.dumps(doc))
        return doc["shots"][0]["id"]

    def run_image(self):
        prop = self.ws.propose("demo", "image", "s01")
        self.ws.approve_human("demo", prop["id"])
        return self.ws.execute("demo", prop["id"])

    def test_prompt_edit_keeps_budget_valid(self):
        self.edit_shot(prompt="a completely different prompt")
        self.assertIn("file", self.run_image())

    def test_seconds_change_voids_budget_with_structured_diff(self):
        shot_id = self.edit_shot(seconds=8)
        prop = self.ws.propose("demo", "image", "s01")
        self.ws.approve_human("demo", prop["id"])
        with self.assertRaises(ServiceError) as ctx:
            self.ws.execute("demo", prop["id"])
        diff = ctx.exception.diff
        self.assertIn({"field": "seconds", "id": shot_id, "from": 4, "to": 8}, diff["changes"])
        self.assertIsNotNone(diff["approved_estimate"])
        self.assertIsNotNone(diff["new_estimate"])
        self.assertIn("Budget out of date", str(ctx.exception))
        self.assertEqual(costlog.read_log(self.p), [])


from tests.test_flow import ANSWERS, Base  # noqa: E402


class BatchTests(Base):
    def setUp(self):
        super().setUp()
        self.interview()
        self.ws.estimate("demo", 0.2)
        self.ws.approve_budget("demo")
        b = json.loads((self.p / "budget.json").read_text())
        b["stop_loss"] = 100
        (self.p / "budget.json").write_text(json.dumps(b))

    def approved_batch(self):
        batch = self.ws.batches.create("demo")
        return self.ws.batches.approve("demo", batch["id"], batch["batch_hash"])

    def test_create_freezes_exact_items_and_needs_human_approval(self):
        batch = self.ws.batches.create("demo", actor="mcp")
        self.assertEqual(batch["status"], "awaiting_approval")
        self.assertEqual(batch["total"], round(sum(i["price"] for i in batch["items"]), 6))
        self.assertTrue(all(i["request_hash"] and i["model"] for i in batch["items"]))
        self.assertTrue((self.p / "batches" / f"{batch['id']}.json").is_file())
        with self.assertRaises(ServiceError):                                   # not approved: cannot run
            self.ws.batches.run("demo", batch["id"])
        with self.assertRaises(ServiceError):                                   # approval is of one exact plan
            self.ws.batches.approve("demo", batch["id"], "0" * 64)
        self.assertEqual(costlog.read_log(self.p), [])

    def test_tampered_batch_file_is_refused(self):
        batch = self.ws.batches.create("demo")
        f = self.p / "batches" / f"{batch['id']}.json"
        doc = json.loads(f.read_text())
        doc["items"][0]["price"] = 0.001
        f.write_text(json.dumps(doc))
        with self.assertRaises(ServiceError):
            self.ws.batches.get("demo", batch["id"])

    def test_approved_batch_runs_every_item_through_its_own_proposal(self):
        batch = self.approved_batch()
        done = self.ws.batches.run("demo", batch["id"])
        self.assertEqual(done["status"], "done")
        self.assertEqual([i["status"] for i in done["items"]], ["done"] * len(batch["items"]))
        rows = costlog.read_log(self.p)
        self.assertEqual(len(rows), len(batch["items"]))
        used = [x for x in json.loads((self.p / "proposals.json").read_text()) if x["status"] == "used"]
        self.assertEqual(len(used), len(batch["items"]))
        with self.assertRaises(ServiceError):                                   # a finished batch cannot run twice
            self.ws.batches.run("demo", batch["id"])

    def test_changed_request_stops_that_item_and_keeps_finished_ones(self):
        batch = self.approved_batch()
        clip = next(i for i in batch["items"] if i["kind"] == "clip")
        doc = json.loads((self.p / "shots.json").read_text())
        next(s for s in doc["shots"] if s["id"] == clip["target"])["prompt"] = "something else entirely"  # prompt only: budget stays valid
        (self.p / "shots.json").write_text(json.dumps(doc))
        res = self.ws.batches.run("demo", batch["id"])
        self.assertEqual(res["status"], "needs_reapproval")
        statuses = {(i["kind"], i["target"]): i["status"] for i in res["items"]}
        self.assertEqual(statuses[("clip", clip["target"])], "needs_reapproval")
        self.assertEqual(statuses[("image", "s01")], "done")
        self.assertIn("request changed", next(i for i in res["items"] if i["target"] == clip["target"] and i["kind"] == "clip")["changes"])
        self.assertEqual(len(costlog.read_log(self.p)), sum(1 for s in statuses.values() if s == "done"))

    def test_changed_model_stops_item_before_any_proposal(self):
        batch = self.approved_batch()
        pipeline = self.ws.pipeline_domain
        real = pipeline._item_price
        with patch.object(pipeline, "_item_price", side_effect=lambda p, k, t: (lambda r: (r[0], "other/model"))(real(p, k, t))):
            res = self.ws.batches.run("demo", batch["id"])
        self.assertEqual(res["status"], "needs_reapproval")
        self.assertEqual(res["items"][0]["status"], "needs_reapproval")
        self.assertFalse((self.p / "proposals.json").exists())
        self.assertEqual(costlog.read_log(self.p), [])


try:
    from fastapi.testclient import TestClient
    from server.app import create_app
    HAVE_API = True
except Exception:  # pragma: no cover
    HAVE_API = False


@unittest.skipUnless(HAVE_API, "needs fastapi + httpx")
class BatchApiTests(unittest.TestCase):
    def setUp(self):
        HERM.all_test(self)
        self.app = create_app(tempfile.mkdtemp(), token="tok", static_dir="/nonexistent")
        self.c = TestClient(self.app)
        self.S = {"x-aistudio-token": "tok"}
        key = self.c.post("/api/keys", json={"name": "agent"}, headers=self.S).json()["key"]
        self.A = {"x-aistudio-token": key}
        self.c.post("/api/projects", json={"name": "demo", "test_pipeline": True}, headers=self.S)
        for text in ["hello"] + ANSWERS + ["skip"]:
            self.c.post("/api/projects/demo/chat", json={"text": text}, headers=self.S)
        self.c.post("/api/projects/demo/estimate", json={"failure": 0.2}, headers=self.S)
        self.c.post("/api/projects/demo/budget/approve", headers=self.S)

    def test_agent_key_can_create_and_list_but_never_approve_or_run(self):
        made = self.c.post("/api/projects/demo/batches", headers=self.A)
        self.assertEqual(made.status_code, 200, made.text)
        batch = made.json()
        self.assertEqual(batch["status"], "awaiting_approval")
        self.assertEqual(batch["actor"], "api-key")
        self.assertEqual(len(self.c.get("/api/projects/demo/batches", headers=self.A).json()["batches"]), 1)
        self.assertEqual(self.c.get(f"/api/projects/demo/batches/{batch['id']}", headers=self.A).status_code, 200)
        base = f"/api/projects/demo/batches/{batch['id']}"
        self.assertEqual(self.c.post(f"{base}/approve", json={"batch_hash": batch["batch_hash"]}, headers=self.A).status_code, 403)
        self.assertEqual(self.c.post(f"{base}/run", headers=self.A).status_code, 403)
        self.assertEqual(self.c.get(base, headers=self.A).json()["status"], "awaiting_approval")

    def test_human_session_approves_then_runs_to_completion(self):
        batch = self.c.post("/api/projects/demo/batches", headers=self.S).json()
        base = f"/api/projects/demo/batches/{batch['id']}"
        job = self.c.post(f"{base}/run", headers=self.S).json()["job"]  # not approved: the job fails and nothing runs
        for _ in range(50):
            if self.c.get(f"/api/jobs/{job}", headers=self.S).json()["status"] != "running":
                break
        self.assertEqual(self.c.get(f"/api/jobs/{job}", headers=self.S).json()["status"], "error")
        self.assertEqual(self.c.get(base, headers=self.S).json()["status"], "awaiting_approval")
        self.assertEqual(self.c.post(f"{base}/approve", json={"batch_hash": batch["batch_hash"]}, headers=self.S).json()["status"], "approved")
        job = self.c.post(f"{base}/run", headers=self.S).json()["job"]
        import time
        for _ in range(100):
            state = self.c.get(f"/api/jobs/{job}", headers=self.S).json()
            if state["status"] != "running":
                break
            time.sleep(0.1)
        self.assertEqual(state["status"], "done", state)
        self.assertEqual(self.c.get(base, headers=self.S).json()["status"], "done")


class BatchMcpTests(unittest.TestCase):
    def test_generate_all_plan_returns_unapproved_batch_and_confirm_is_refused(self):
        from aistudio import mcp_server
        HERM.all_test(self)
        ws = Workspace(tempfile.mkdtemp())
        ws.create_project("demo")
        for text in ["hello"] + ANSWERS + ["skip"]:
            ws.chat_send("demo", text)
        ws.estimate("demo", 0.2)
        ws.approve_budget("demo")
        batch = mcp_server.TOOLS["generate_all_plan"][2](ws, {"name": "demo"})
        self.assertEqual((batch["status"], batch["actor"]), ("awaiting_approval", "mcp"))
        with self.assertRaises(ServiceError):
            mcp_server._approve_batch_mcp(ws, {"name": "demo", "id": batch["id"], "confirm": True})
        out = mcp_server._approve_batch_mcp(ws, {"name": "demo", "id": batch["id"]})   # no elicitation: code challenge only
        self.assertTrue(out["approval_needed"])
        self.assertEqual(ws.batches.get("demo", batch["id"])["status"], "awaiting_approval")
        with self.assertRaises(ServiceError):
            mcp_server._run_batch_mcp(ws, {"name": "demo", "id": batch["id"]})


if __name__ == "__main__":
    unittest.main()
