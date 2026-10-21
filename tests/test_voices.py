import tests._hermetic as HERM
import tempfile
import unittest
from pathlib import Path
from fastapi.testclient import TestClient
from server.app import create_app


class TestVoicesRoute(unittest.TestCase):
    def setUp(self):
        HERM.all_test(self)
        self.root = Path(tempfile.mkdtemp())
        self.app = create_app(str(self.root), token="tok", static_dir="/nonexistent")
        self.client = TestClient(self.app)

    def test_voices_requires_token(self):
        res = self.client.get("/api/voices")
        self.assertEqual(res.status_code, 401)

    def test_voices_returns_list_with_human_token(self):
        res = self.client.get("/api/voices", headers={"x-aistudio-token": "tok"})
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("voices", data)
        self.assertIsInstance(data["voices"], list)
        self.assertGreater(len(data["voices"]), 0)
        voice = data["voices"][0]
        self.assertIn("id", voice)
        self.assertIn("name", voice)
        self.assertIn("provider", voice)


if __name__ == "__main__":
    unittest.main()
