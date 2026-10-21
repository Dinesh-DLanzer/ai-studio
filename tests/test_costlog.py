import csv
import json
import multiprocessing
import os
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch
from aistudio import costlog as C, project_lock


def row(shot, stage="final", attempt="1", cost="0.2"):
    return {"shot": shot, "stage": stage, "attempt": attempt, "cost": cost, "model": "m", "result": "completed"}


def append_in_process(pdir, ready, finished):
    ready.set()
    C.append_log(pdir, row("child"))
    finished.set()


class TestCostlog(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.p = Path(folder.name)

    def write_legacy(self, columns, rows):
        with (self.p / "cost_log.csv").open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=columns)
            writer.writeheader()
            writer.writerows(rows)

    def test_empty(self):
        self.assertEqual(C.read_log(self.p), [])
        self.assertEqual(C.spent(self.p), 0.0)

    def test_append_read_spent(self):
        C.append_log(self.p, row("s01"))
        C.append_log(self.p, row("s02", cost="0.12"))
        C.append_log(self.p, row("s03", cost=""))
        rows = C.read_log(self.p)
        self.assertEqual([r["shot"] for r in rows], ["s01", "s02", "s03"])
        self.assertEqual(list(rows[0].keys()), C.LOG_COLS)
        self.assertEqual(rows[0]["job_id"], "")
        self.assertAlmostEqual(C.spent(self.p), 0.32)
        self.assertEqual((self.p / "cost_log.csv").read_text().splitlines()[0], ",".join(C.LOG_COLS))

    def test_append_migrates_legacy_headers(self):
        for columns in (C.LOG_COLS[:10], C.LOG_COLS[:12], C.LOG_COLS[:13]):
            with self.subTest(columns=columns):
                old = row("old,\nshot")
                if "actor" in columns:
                    old["actor"] = "human"
                self.write_legacy(columns, [old])
                C.append_log(self.p, dict(row("new"), actor="tara", override="yes"))
                rows = C.read_log(self.p)
                self.assertEqual(len(rows), 2)
                self.assertEqual(rows[0]["shot"], old["shot"])
                self.assertEqual(rows[0]["actor"], old.get("actor", ""))
                self.assertEqual(rows[0]["override"], "")
                self.assertEqual(rows[1]["actor"], "tara")
                self.assertEqual(rows[1]["override"], "yes")
                self.assertAlmostEqual(C.spent(self.p), 0.4)
                with (self.p / "cost_log.csv").open(newline="", encoding="utf-8") as f:
                    records = list(csv.reader(f))
                self.assertEqual(records[0], C.LOG_COLS)
                self.assertTrue(all(len(record) == len(C.LOG_COLS) for record in records))

    def test_append_recovers_previous_legacy_overflow(self):
        self.write_legacy(C.LOG_COLS[:10], [row("old")])
        overflow = dict(row("overflow"), provider="fake", cost_source="actual", actor="tara", override="yes")
        with (self.p / "cost_log.csv").open("a", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=C.LOG_COLS).writerow(overflow)
        C.append_log(self.p, row("new"))
        rows = C.read_log(self.p)
        self.assertEqual(rows[1]["provider"], "fake")
        self.assertEqual(rows[1]["cost_source"], "actual")
        self.assertEqual(rows[1]["actor"], "tara")
        self.assertEqual(rows[1]["override"], "yes")
        self.assertTrue(all(None not in record for record in rows))
        self.assertAlmostEqual(C.spent(self.p), 0.6)

    def test_append_preserves_unknown_legacy_columns_on_error(self):
        self.write_legacy(C.LOG_COLS + ["future"], [dict(row("old"), future="keep")])
        before = (self.p / "cost_log.csv").read_bytes()
        with self.assertRaises(ValueError):
            C.append_log(self.p, row("new"))
        self.assertEqual((self.p / "cost_log.csv").read_bytes(), before)

    def test_failed_migration_preserves_original_and_cleans_temp_file(self):
        self.write_legacy(C.LOG_COLS[:12], [row("old")])
        before = (self.p / "cost_log.csv").read_bytes()
        with patch.object(C.os, "replace", side_effect=OSError("replace failed")):
            with self.assertRaises(OSError):
                C.append_log(self.p, row("new"))
        self.assertEqual((self.p / "cost_log.csv").read_bytes(), before)
        self.assertEqual(list(self.p.glob(".cost_log.*.tmp")), [])

    def test_empty_file_and_defaults(self):
        (self.p / "cost_log.csv").touch()
        C.append_log(self.p, row("new"))
        self.assertEqual(C.read_log(self.p)[0]["actor"], "local")
        self.assertEqual(C.read_log(self.p)[0]["override"], "no")

    def test_thread_writes_are_serialized_without_flock(self):
        active = 0
        maximum = 0
        state_lock = threading.Lock()

        @contextmanager
        def process_lock(_):
            nonlocal active, maximum
            with state_lock:
                active += 1
                maximum = max(maximum, active)
            try:
                time.sleep(0.002)
                yield
            finally:
                with state_lock:
                    active -= 1

        with patch.object(project_lock, "lock", process_lock):
            with ThreadPoolExecutor(max_workers=8) as pool:
                list(pool.map(lambda i: C.append_log(self.p, row(str(i))), range(24)))
        self.assertEqual(maximum, 1)
        rows = C.read_log(self.p)
        self.assertEqual({record["shot"] for record in rows}, {str(i) for i in range(24)})
        self.assertTrue(all(None not in record for record in rows))

    @unittest.skipUnless(os.name == "posix", "project lock uses POSIX flock")
    def test_append_waits_for_cross_process_project_lock(self):
        ctx = multiprocessing.get_context("spawn")
        ready, finished = ctx.Event(), ctx.Event()
        process = ctx.Process(target=append_in_process, args=(self.p, ready, finished))
        try:
            with project_lock.lock(self.p):
                process.start()
                self.assertTrue(ready.wait(10), "child failed to start")
                self.assertFalse(finished.wait(0.2), "append ignored the project lock")
            process.join(10)
            self.assertEqual(process.exitcode, 0)
            self.assertTrue(finished.is_set())
            self.assertEqual(C.read_log(self.p)[0]["shot"], "child")
        finally:
            if process.is_alive():
                process.terminate()
                process.join(5)

    def test_record_result_updates_one_attempt_without_double_counting(self):
        C.append_log(self.p, dict(row("s01"), result="pending", job_id="job", actor="tara", override="yes"))
        C.append_log(self.p, row("s02", cost="0.3"))
        update = {"shot": "s01", "stage": "final", "attempt": 1, "cost": "0.12", "result": "completed"}
        C.record_result(self.p, update)
        C.record_result(self.p, update)
        rows = C.read_log(self.p)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["job_id"], "job")
        self.assertEqual(rows[0]["actor"], "tara")
        self.assertEqual(rows[0]["override"], "yes")
        self.assertEqual(rows[0]["result"], "completed")
        self.assertAlmostEqual(C.spent(self.p), 0.42)

    def test_record_result_inserts_distinct_stages_and_attempts(self):
        for entry in (row("s01"), row("s01", stage="image"), row("s01", attempt="2")):
            C.record_result(self.p, entry)
        self.assertEqual(len(C.read_log(self.p)), 3)
        self.assertAlmostEqual(C.spent(self.p), 0.6)

    def test_record_result_migrates_legacy_header(self):
        self.write_legacy(C.LOG_COLS[:10], [row("s01")])
        C.record_result(self.p, {"shot": "s01", "stage": "final", "attempt": "1", "cost": "0.1"})
        rows = C.read_log(self.p)
        self.assertEqual(len(rows), 1)
        self.assertEqual(list(rows[0]), C.LOG_COLS)
        self.assertEqual(rows[0]["model"], "m")
        self.assertEqual(rows[0]["actor"], "")
        self.assertEqual(C.spent(self.p), 0.1)

    def test_record_result_and_appends_preserve_all_rows_concurrently(self):
        self.write_legacy(C.LOG_COLS[:12], [dict(row("pending"), result="pending")])

        def write(index):
            if index % 2:
                C.append_log(self.p, row(str(index)))
            else:
                C.record_result(self.p, row("pending", cost="0.1"))

        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(write, range(16)))
        rows = C.read_log(self.p)
        self.assertEqual(len(rows), 9)
        self.assertEqual({record["shot"] for record in rows}, {"pending", *(str(i) for i in range(1, 16, 2))})
        self.assertAlmostEqual(C.spent(self.p), 1.7)

    def test_record_result_rejects_missing_identity_and_unknown_keys(self):
        for key in ("shot", "stage", "attempt"):
            invalid = row("s01")
            del invalid[key]
            with self.subTest(key=key), self.assertRaises(ValueError):
                C.record_result(self.p, invalid)
        with self.assertRaises(KeyError):
            C.record_result(self.p, dict(row("s01"), bogus=1))
        self.assertEqual(C.read_log(self.p), [])

    def test_record_result_rejects_ambiguous_duplicate_identity(self):
        C.append_log(self.p, row("s01"))
        C.append_log(self.p, row("s01"))
        before = (self.p / "cost_log.csv").read_bytes()
        with self.assertRaises(ValueError):
            C.record_result(self.p, row("s01", cost="0.1"))
        self.assertEqual((self.p / "cost_log.csv").read_bytes(), before)

    def test_extra_key(self):
        with self.assertRaises(KeyError):
            C.append_log(self.p, dict(row("s01"), bogus=1))

    def test_split(self):
        C.append_log(self.p, row("s01"))
        C.append_log(self.p, row("s01", attempt="2", cost="0.3"))
        C.append_log(self.p, row("d01", stage="image", cost="0.036"))
        C.append_log(self.p, row("d02", stage="image", cost="0.04"))
        (self.p / "discarded.json").write_text(json.dumps([
            {"file": "clips/_discarded/s01_final_a1.mp4", "cost": 0.2, "reason": "x"},
            {"file": "stills/_discarded/d01.png", "cost": 0.036, "reason": "y"}]))
        r = C.split(self.p)
        self.assertAlmostEqual(r["discarded"], 0.236)
        self.assertAlmostEqual(r["used"], 0.34)
        self.assertAlmostEqual(r["total"], 0.576)

    def test_split_no_discard_file(self):
        C.append_log(self.p, row("s01"))
        self.assertEqual(C.split(self.p), {"used": 0.2, "discarded": 0.0, "total": 0.2})


if __name__ == "__main__":
    unittest.main()
