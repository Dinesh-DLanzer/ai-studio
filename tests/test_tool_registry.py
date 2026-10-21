import tests._hermetic as HERM  # noqa: F401
import unittest

from aistudio import mcp_server, tool_registry as R


class TestToolRegistry(unittest.TestCase):
    def test_mcp_reads_the_registry_table(self):
        self.assertIs(mcp_server.TOOLS, R.TOOLS)
        self.assertEqual([t["name"] for t in mcp_server.tool_list()], list(R.TOOLS))

    def test_every_tool_is_classified_with_a_valid_class(self):
        self.assertEqual(set(R.META), set(R.TOOLS))
        self.assertTrue(all(m["cost_class"] in R.CLASSES for m in R.META.values()))

    def test_money_and_human_tools_are_never_crew_tools(self):
        crew = set(R.crew_tools())
        for n in ("approve_budget", "approve_proposal", "approve_batch", "run_proposal", "run_batch", "approve_shot", "reject_proposal",
                  "set_max_attempts", "estimate", "discard", "restore", "delete_project", "restore_trash", "upload_image", "create_project"):
            self.assertIn(R.cost_class(n), ("approval", "human_only"), n)
            self.assertNotIn(n, crew, n)
        self.assertEqual([c["name"] for c in R.crew_catalogue(["approve_budget", "run_proposal", "get_project"])], ["get_project"])
        self.assertTrue(all(R.cost_class(n) in ("free", "paid") for n in crew))

    def test_any_tool_that_approves_overrides_or_takes_a_code_is_not_crew(self):
        for n in R.TOOLS:
            props = R.TOOLS[n][1]["properties"]
            if n.startswith(("approve", "run_", "delete", "restore")) or "override" in props or "code" in props:
                self.assertNotIn(n, R.crew_tools(), n)


if __name__ == "__main__":
    unittest.main()
