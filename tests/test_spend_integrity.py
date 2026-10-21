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


if __name__ == "__main__":
    unittest.main()
