import multiprocessing
import sqlite3
import tempfile
import threading
import unittest

from aistudio import store


def _writer(root, n, tag):
    for i in range(n):
        store.execute(root, "INSERT INTO jobs (id, project, kind, state, created, updated) VALUES (?,?,?,?,?,?)",
                      (f"{tag}-{i}", "p", "export", "queued", 0, 0))


class TestStore(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()

    def test_migrates_once_and_sets_version(self):
        store.connect(self.root)
        con = sqlite3.connect(store.db_path(self.root))
        self.assertEqual(con.execute("PRAGMA user_version").fetchone()[0], len(store.MIGRATIONS))
        self.assertEqual(con.execute("PRAGMA journal_mode").fetchone()[0], "wal")
        con.close()
        store.close_all()
        store.connect(self.root)    # reopen: no error, no re-migration

    def test_defaults_and_rollback(self):
        store.execute(self.root, "INSERT INTO jobs (id, project, kind, state, created, updated) VALUES ('a','p','export','queued',0,0)")
        row = store.query(self.root, "SELECT tenant_id, actor FROM jobs")[0]
        self.assertEqual((row["tenant_id"], row["actor"]), ("local", "local"))
        with self.assertRaises(RuntimeError):
            with store.transaction(self.root) as tx:
                tx.execute("DELETE FROM jobs")
                raise RuntimeError
        self.assertEqual(len(store.query(self.root, "SELECT id FROM jobs")), 1)

    def test_library_schema_has_local_tenant_and_actor(self):
        store.execute(self.root, "INSERT INTO items (id, project, kind, file) VALUES ('i','p','image','stills/a.png')")
        row = store.query(self.root, "SELECT tenant_id, actor FROM items WHERE id='i'")[0]
        self.assertEqual((row["tenant_id"], row["actor"]), ("local", "local"))

    def test_threads_and_processes_write_concurrently(self):
        procs = [multiprocessing.Process(target=_writer, args=(self.root, 40, f"p{i}")) for i in range(2)]
        threads = [threading.Thread(target=_writer, args=(self.root, 40, f"t{i}")) for i in range(2)]
        for x in procs + threads:
            x.start()
        for x in procs + threads:
            x.join(60)
        for x in procs:
            self.assertEqual(x.exitcode, 0)
        self.assertEqual(store.query(self.root, "SELECT COUNT(*) AS n FROM jobs")[0]["n"], 160)


if __name__ == "__main__":
    unittest.main()
