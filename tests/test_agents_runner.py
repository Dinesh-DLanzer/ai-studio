"""Unit tests for terminal agent detection and runner."""
import tempfile
import unittest
from fastapi.testclient import TestClient
from aistudio.service import Workspace
from server.app import create_app
import tests._hermetic as HERM


class TestAgentsRunner(unittest.TestCase):
    def setUp(self):
        HERM.all_test(self)
        self.home = tempfile.mkdtemp()
        self.ws = Workspace(self.home)
        self.app = create_app(root=self.home, token="test-token")
        self.client = TestClient(self.app)

    def test_list_agents(self):
        agents = self.ws.list_agents()
        self.assertIsInstance(agents, list)
        self.assertTrue(len(agents) >= 4)
        ids = [a["id"] for a in agents]
        self.assertIn("claude", ids)
        self.assertIn("agy", ids)
        self.assertIn("opencode", ids)

    def test_api_agents_list(self):
        res = self.client.get("/api/agents?token=test-token")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("agents", data)
        self.assertTrue(len(data["agents"]) >= 3)

    def test_abort_non_running_agent(self):
        ok = self.ws.abort_agent("claude")
        self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main()
