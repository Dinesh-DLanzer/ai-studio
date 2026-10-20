"""Tests for scriptable --json and non-interactive CLI flags."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from aistudio import cli
from aistudio.service import Workspace
from tests.test_story_convert import MD
import tests._hermetic as HERM


class TestCliJson(unittest.TestCase):
    def setUp(self):
        HERM.all_test(self)
        self.home = tempfile.mkdtemp()
        os.environ["AISTUDIO_HOME"] = self.home
        self.ws = Workspace(self.home)
        self.ws.create_project("demo", test_pipeline=True)
        self.ws.put_text("demo", "Story.md", MD)
        self.ws.convert_story("demo")
        self.ws.estimate("demo")
        self.lines = []

    def run_cli(self, argv):
        self.lines = []
        return cli.main(argv, ask=lambda q: "no", out=self.lines.append)

    def test_projects_json(self):
        code = self.run_cli(["projects", "--json"])
        self.assertEqual(code, 0)
        data = json.loads("".join(self.lines))
        self.assertIsInstance(data, list)
        self.assertEqual(data[0]["name"], "demo")

    def test_overview_json(self):
        code = self.run_cli(["overview", "demo", "--json"])
        self.assertEqual(code, 0)
        data = json.loads("".join(self.lines))
        self.assertEqual(data["name"], "demo")
        self.assertIn("shots", data)

    def test_convert_story_json(self):
        code = self.run_cli(["convert-story", "demo", "--json"])
        self.assertEqual(code, 0)
        data = json.loads("".join(self.lines))
        self.assertIn("shots", data)

    def test_verify_json(self):
        code = self.run_cli(["verify", "demo", "--json"])
        self.assertEqual(code, 0)
        data = json.loads("".join(self.lines))
        self.assertIn("story", data)

    def test_non_interactive_approvals(self):
        # Without -y, ask returns "no" and it's rejected
        self.run_cli(["approve-budget", "demo"])
        self.assertFalse(self.ws.overview("demo")["budget"]["approved"])

        # --yes cannot impersonate a human budget approval
        code = self.run_cli(["approve-budget", "demo", "-y"])
        self.assertEqual(code, 1)
        self.assertFalse(self.ws.overview("demo")["budget"]["approved"])

    def test_agent_setup(self):
        code = self.run_cli(["agent-setup", "all"])
        self.assertEqual(code, 0)
        self.assertTrue((Path(self.home) / ".mcp.json").exists())
        self.assertTrue((Path(self.home) / ".agents" / "skills" / "aistudio" / "SKILL.md").exists())


if __name__ == "__main__":
    unittest.main()
