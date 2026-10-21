import tempfile
import unittest
from pathlib import Path

from tests import _hermetic  # noqa: F401  (no network, no keychain)
from aistudio import costlog
from aistudio.domain.costs import CostDomain


class _Runner:
    def __init__(self, res):
        self.res = res

    def fetch_video(self, job, req):
        return self.res


class _WS:
    def __init__(self, p, res):
        self.p, self._runner = p, _Runner(res)

    def pdir(self, name):
        return self.p

    def runner(self):
        return self._runner


class SyncFloorTests(unittest.TestCase):
    def _run(self, res):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            (p / "clips").mkdir()
            costlog.append_log(p, {"shot": "s01", "stage": "final", "model": "m", "attempt": "1", "job_id": "j1", "seconds": "5",
                                   "resolution": "720p", "cost": "0.60", "result": "pending", "provider": "x", "cost_source": "estimated"})
            CostDomain(_WS(p, res)).sync("demo")
            return costlog.read_log(p)[0]

    def test_computed_cost_never_drops_below_the_logged_quote(self):
        row = self._run({"status": "done", "bytes": b"x", "cost": 0.40, "cost_source": "computed"})
        self.assertEqual(float(row["cost"]), 0.60)

    def test_provider_reported_cost_is_trusted(self):
        row = self._run({"status": "done", "bytes": b"x", "cost": 0.40, "cost_source": "reported"})
        self.assertEqual(float(row["cost"]), 0.40)

    def test_failed_job_is_not_floored(self):
        row = self._run({"status": "failed", "cost": 0.0, "cost_source": "reported"})
        self.assertEqual(float(row["cost"]), 0.0)


if __name__ == "__main__":
    unittest.main()
