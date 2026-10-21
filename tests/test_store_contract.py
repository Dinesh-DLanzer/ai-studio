import tempfile
import unittest

from aistudio import store


class StoreContract:
    """Backend-neutral contract. Subclass and provide a backend for additional implementations."""
    def test_execute_query_and_transaction(self):
        root = tempfile.mkdtemp()
        store.execute(root, "CREATE TABLE contract (id TEXT PRIMARY KEY, value TEXT NOT NULL)")
        self.assertEqual(store.execute(root, "INSERT INTO contract VALUES (?, ?)", ("a", "one")), 1)
        self.assertEqual(store.query(root, "SELECT * FROM contract WHERE id = ?", ("a",)), [{"id": "a", "value": "one"}])
        with store.transaction(root) as tx:
            tx.execute("INSERT INTO contract VALUES (?, ?)", ("b", "two"))
            self.assertEqual(tx.query("SELECT value FROM contract ORDER BY id"), [{"value": "one"}, {"value": "two"}])


class SQLiteStoreContract(StoreContract, unittest.TestCase):
    def setUp(self):
        store.set_backend(store.SQLiteBackend())

    def tearDown(self):
        store.close_all()
        store.set_backend(None)


if __name__ == "__main__":
    unittest.main()
