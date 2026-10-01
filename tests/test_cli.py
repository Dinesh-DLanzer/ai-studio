import tests._hermetic as HERM  # noqa: F401  (no real key or network in tests)
import tempfile, unittest, os
from aistudio import cli
from aistudio.service import Workspace
from tests.test_story_convert import MD


class TestCli(unittest.TestCase):
    def setUp(self):
        HERM.all_test(self)
        self.home = tempfile.mkdtemp()
        os.environ["AISTUDIO_HOME"] = self.home
        self.ws = Workspace(self.home)
        self.ws.create_project("demo"); self.ws.put_text("demo", "Story.md", MD); self.ws.convert_story("demo"); self.ws.estimate("demo", 0.2)
        self.lines = []

    def run_cli(self, argv, answer="yes"):
        return cli.main(argv, ask=lambda q: answer, out=self.lines.append)

    def test_budget_and_proposal_approval(self):
        self.run_cli(["approve-budget", "demo"], "no")
        self.assertFalse(self.ws.overview("demo")["budget"]["approved"])
        self.run_cli(["approve-budget", "demo"])
        self.assertTrue(self.ws.overview("demo")["budget"]["approved"])
        prop = self.ws.propose("demo", "image", "s01")
        self.run_cli(["approve", "demo", prop["id"]], "no")
        self.assertEqual(self.ws.proposal_status("demo", prop["id"])["status"], "pending")
        self.run_cli(["approve", "demo", prop["id"]], "yes")
        self.assertEqual(self.ws.proposal_status("demo", prop["id"])["status"], "approved")

    def test_errors(self):
        self.assertEqual(self.run_cli(["pending", "nope"]), 1)


if __name__ == "__main__":
    unittest.main()
