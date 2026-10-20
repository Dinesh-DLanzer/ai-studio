import unittest

from server import api_docs


class TestAgentAllowed(unittest.TestCase):
    def test_agent_keys_cannot_approve_or_use_human_routes(self):
        denied = {
            ("POST", "/api/projects/{name}/budget/approve"),
            ("POST", "/api/projects/{name}/proposals/{pid}/approve"),
            ("POST", "/api/projects/{name}/proposals/{pid}/approve-human"),
            ("POST", "/api/projects/{name}/proposals/{pid}/reject"),
            ("POST", "/api/projects/{name}/shots/{shot}/approve"),
        }
        for method, path in denied:
            self.assertFalse(api_docs.agent_allowed(method, path), (method, path))
        self.assertFalse(api_docs.agent_allowed("GET", "/api/approval-notifications"))

    def test_execute_route_is_only_for_already_approved_proposals(self):
        route = ("POST", "/api/projects/{name}/proposals/{pid}/execute")
        self.assertTrue(api_docs.agent_allowed(*route))
        self.assertIn("ALREADY approved", api_docs.DOCS[f"{route[0]} {route[1]}"]["summary"])
        self.assertNotIn("approve it", api_docs.DOCS[f"{route[0]} {route[1]}"]["summary"].lower())

    def test_proposal_only_paid_tools_are_agent_reachable(self):
        self.assertFalse(api_docs.agent_allowed("POST", "/api/projects/{name}/proposals/{pid}/reject"))
        for path in (
            "/api/projects/{name}/proposals",
            "/api/projects/{name}/stills/{shot_id}/edit",
            "/api/projects/{name}/clips/{shot_id}/extend",
            "/api/projects/{name}/character/analyze",
        ):
            self.assertTrue(api_docs.agent_allowed("POST", path), path)


if __name__ == "__main__":
    unittest.main()
