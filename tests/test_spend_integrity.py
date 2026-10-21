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


if __name__ == "__main__":
    unittest.main()
