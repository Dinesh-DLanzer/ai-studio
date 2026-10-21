"""The msvcrt branch of project_lock, exercised with a fake msvcrt (real Windows is not tested here)."""
import errno
import sys
import tempfile
import types
import unittest
from unittest import mock

from aistudio import project_lock


def fake_msvcrt(fail_first=0, fail_errno=errno.EACCES):
    calls = {"lock": 0, "unlock": 0, "seeks": []}
    mod = types.ModuleType("msvcrt")
    mod.LK_LOCK, mod.LK_UNLCK = 1, 2

    def locking(fd, mode, nbytes):
        if mode == mod.LK_LOCK:
            calls["lock"] += 1
            if calls["lock"] <= fail_first:
                raise OSError(fail_errno, "contended")
        else:
            calls["unlock"] += 1
    mod.locking = locking
    return mod, calls


class WindowsLockTests(unittest.TestCase):
    def run_with(self, mod):
        with mock.patch.dict(sys.modules, {"fcntl": None, "msvcrt": mod}):      # fcntl import fails -> the msvcrt backend is chosen
            with tempfile.TemporaryDirectory() as d, project_lock.lock(d):
                pass

    def test_lock_and_unlock_are_paired(self):
        mod, calls = fake_msvcrt()
        self.run_with(mod)
        self.assertEqual((calls["lock"], calls["unlock"]), (1, 1))

    def test_contention_is_retried_until_the_lock_is_free(self):
        mod, calls = fake_msvcrt(fail_first=3)
        with mock.patch("aistudio.project_lock.time.sleep"):
            self.run_with(mod)
        self.assertEqual(calls["lock"], 4)

    def test_a_real_error_is_not_retried_forever_and_refuses_to_run(self):
        mod, calls = fake_msvcrt(fail_first=99, fail_errno=errno.EBADF)
        with self.assertRaisesRegex(RuntimeError, "spend lock unavailable"):
            self.run_with(mod)
        self.assertEqual(calls["lock"], 1)

    def test_no_backend_refuses_unsafe_execution(self):
        with mock.patch.dict(sys.modules, {"fcntl": None, "msvcrt": None}):
            with tempfile.TemporaryDirectory() as d, self.assertRaisesRegex(RuntimeError, "spend lock unavailable"):
                with project_lock.lock(d):
                    pass


if __name__ == "__main__":
    unittest.main()
