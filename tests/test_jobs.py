import multiprocessing
import tempfile
import threading
import time
import unittest

from aistudio import jobs, store
from aistudio.domain.common import ServiceError


def wait(pred, secs=5):
    end = time.time() + secs
    while time.time() < end:
        if pred():
            return True
        time.sleep(0.01)
    return False


def _enqueuer(root, n):
    for i in range(n):
        jobs.enqueue(root, "p", "export", target=str(i))


class TestLedger(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.runners = []

    def tearDown(self):
        for r in self.runners:
            r.shutdown()

    def runner(self, handlers, **kw):
        r = jobs.JobRunner(self.root, handlers, **kw)
        self.runners.append(r)
        return r

    def state(self, jid):
        return jobs.get(self.root, jid)["state"]

    def test_completed_failed_and_progress(self):
        def ok(job, progress):
            progress(40)
            return {"file": "a.mp4"}

        def bad(job, progress):
            raise ServiceError("budget stale")
        r = self.runner({"export": ok, "execute": bad})
        a, b = r.submit("p", "export"), r.submit("p", "execute", proposal_id="x")
        self.assertTrue(wait(lambda: self.state(a["id"]) == "completed" and self.state(b["id"]) == "failed"))
        done = jobs.get(self.root, a["id"])
        self.assertEqual((done["result"], done["progress"], done["attempts"], done["tenant_id"], done["actor"]), ({"file": "a.mp4"}, 100.0, 1, "local", "local"))
        self.assertEqual(jobs.get(self.root, b["id"])["error"], "budget stale")
        self.assertEqual({j["id"] for j in jobs.list_jobs(self.root, project="p")}, {a["id"], b["id"]})
        self.assertEqual(jobs.list_jobs(self.root, project="other"), [])

    def test_concurrency_cap_per_provider(self):
        live, peak, lock, gate = [0], [0], threading.Lock(), threading.Event()

        def slow(job, progress):
            with lock:
                live[0] += 1
                peak[0] = max(peak[0], live[0])
            gate.wait(5)
            with lock:
                live[0] -= 1
            return {}
        r = self.runner({"export": slow})
        ids = [r.submit("p", "export", provider="fake")["id"] for _ in range(6)]
        self.assertTrue(wait(lambda: live[0] == 2))
        time.sleep(0.2)
        self.assertEqual(live[0], 2)
        self.assertEqual(sum(self.state(i) == "queued" for i in ids), 4)
        gate.set()
        self.assertTrue(wait(lambda: all(self.state(i) == "completed" for i in ids)))
        self.assertEqual(peak[0], 2)

    def test_cancel_queued_running_and_pending(self):
        gate = threading.Event()

        def blocker(job, progress):
            gate.wait(5)
            progress(50)       # sees the cancel request
            return {}
        r = self.runner({"export": blocker}, concurrency=lambda p: 1)
        first, second = r.submit("p", "export"), r.submit("p", "export")
        self.assertTrue(wait(lambda: self.state(first["id"]) == "running"))
        self.assertEqual(jobs.cancel(self.root, second["id"])["state"], "cancelled")
        self.assertEqual(jobs.cancel(self.root, first["id"])["state"], "running")   # asked to stop
        gate.set()
        self.assertTrue(wait(lambda: self.state(first["id"]) == "cancelled"))
        self.assertEqual(self.state(second["id"]), "cancelled")     # the claim loses against the cancel
        pend = jobs.enqueue(self.root, "p", "execute", state="provider_pending")
        c = jobs.cancel(self.root, pend["id"])
        self.assertEqual(c["state"], "cancelled")
        self.assertIn("may still bill", c["error"])
        self.assertIsNone(jobs.cancel(self.root, "nope"))

    def test_pending_result_then_polling_completes(self):
        outcome = [None]
        r = self.runner({"execute": lambda job, progress: {"pending": True, "job_id": "prov-1"}},
                        poll=lambda job: outcome[0], poll_interval=0.01)
        j = r.submit("p", "execute")
        self.assertTrue(wait(lambda: self.state(j["id"]) == "provider_pending"))
        self.assertEqual(jobs.get(self.root, j["id"])["provider_job"], "prov-1")
        outcome[0] = "completed"
        self.assertTrue(wait(lambda: self.state(j["id"]) == "completed"))

    def test_restart_reconciliation(self):
        e = self.root
        paid_running = jobs.enqueue(e, "p", "execute", state="running")
        paid_queued = jobs.enqueue(e, "p", "execute")
        batch_running = jobs.enqueue(e, "p", "batch", state="running")
        child_running = jobs.enqueue(e, "p", "execute", batch_id=batch_running["id"], state="running")
        free_running = jobs.enqueue(e, "p", "export", state="running")
        pending = jobs.enqueue(e, "p", "execute", state="provider_pending")
        done = jobs.enqueue(e, "p", "execute", state="completed")
        calls = []
        ran = []
        # a "new server process": fresh runner on the same ledger
        r = self.runner({"export": lambda job, progress: ran.append(job["id"]) or {}, "execute": lambda job, progress: ran.append(job["id"]) or {}},
                        poll=lambda job: calls.append(job["id"]) and None, poll_interval=0.01)
        r.reconcile()
        self.assertTrue(wait(lambda: self.state(free_running["id"]) == "completed"))
        for j in (paid_running, paid_queued, batch_running, child_running):
            self.assertEqual(self.state(j["id"]), "needs_sync")
        self.assertEqual(self.state(pending["id"]), "provider_pending")
        self.assertEqual(self.state(done["id"]), "completed")
        self.assertEqual(ran, [free_running["id"]])      # no paid job was executed again
        self.assertTrue(wait(lambda: pending["id"] in calls))

    def test_prune_old_finished_only(self):
        old = jobs.enqueue(self.root, "p", "export", state="completed")
        keep = jobs.enqueue(self.root, "p", "export", state="needs_sync")
        store.execute(self.root, "UPDATE jobs SET updated = ?", (time.time() - 31 * 86400,))
        jobs.prune(self.root)
        self.assertIsNone(jobs.get(self.root, old["id"]))
        self.assertIsNotNone(jobs.get(self.root, keep["id"]))

    def test_two_processes_enqueue_at_once(self):
        procs = [multiprocessing.Process(target=_enqueuer, args=(self.root, 30)) for _ in range(3)]
        for p in procs:
            p.start()
        for p in procs:
            p.join(60)
            self.assertEqual(p.exitcode, 0)
        rows = jobs.list_jobs(self.root)
        self.assertEqual(len(rows), 90)
        self.assertEqual(len({r["id"] for r in rows}), 90)


if __name__ == "__main__":
    unittest.main()
