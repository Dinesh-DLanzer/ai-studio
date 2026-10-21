import tests._hermetic as HERM  # noqa: F401
import json
import os
import tempfile
import unittest

try:
    from fastapi.testclient import TestClient
    from server.app import create_app
    HAVE = True
except Exception:
    HAVE = False
from aistudio import cli, costlog, tool_registry as R
from aistudio.service import Workspace
from tests.test_recipes_plan import PNG

BODY = {"inputs": {"product": "stills/product.png", "setting": "studio", "headline": "Hi"}}


@unittest.skipUnless(HAVE, "needs the venv with fastapi + httpx")
class TestRecipeRoutes(unittest.TestCase):
    def setUp(self):
        HERM.all_test(self)
        self.root = tempfile.mkdtemp()
        self.app = create_app(self.root, token="tok", static_dir="/nonexistent")
        self.c = TestClient(self.app)
        self.S = {"x-aistudio-token": "tok"}
        self.A = {"x-aistudio-token": self.c.post("/api/keys", json={"name": "agent"}, headers=self.S).json()["key"]}
        self.c.post("/api/projects", json={"name": "demo", "test_pipeline": True}, headers=self.S)
        self.p = self.app.state.ws.pdir("demo")
        (self.p / "stills").mkdir(exist_ok=True)
        (self.p / "stills" / "product.png").write_bytes(PNG)
        HERM.register_test_media(self.p, "stills/product.png")
        self.url = "/api/projects/demo/recipes/product-ad-9x16/plan"

    def test_list_is_readable_by_an_api_key_and_flags_unavailable(self):
        r = self.c.get("/api/recipes?project=demo", headers=self.A)
        self.assertEqual(r.status_code, 200)
        by = {x["id"]: x for x in r.json()["recipes"]}
        self.assertTrue(by["product-ad-9x16"]["available"])
        self.assertFalse(by["headshot"]["available"])
        only = self.c.get("/api/recipes?available=1", headers=self.A).json()["recipes"]
        self.assertNotIn("headshot", [x["id"] for x in only])

    def test_only_the_human_session_plans_and_an_api_key_cannot_approve_or_run(self):
        self.assertEqual(self.c.post(self.url, json=BODY, headers=self.A).status_code, 403)
        r = self.c.post(self.url, json=BODY, headers=self.S)
        self.assertEqual(r.status_code, 200, r.text)
        b = r.json()
        self.assertEqual((b["status"], b["actor"]), ("awaiting_approval", "local"))
        self.assertEqual(b["total"], round(sum(i["price"] for i in b["items"]), 6))
        for path, body in ((f"/api/projects/demo/batches/{b['id']}/approve", {"batch_hash": b["batch_hash"]}), (f"/api/projects/demo/batches/{b['id']}/run", {})):
            self.assertEqual(self.c.post(path, json=body, headers=self.A).status_code, 403, path)
        self.assertEqual(self.c.get(f"/api/projects/demo/batches/{b['id']}", headers=self.S).json()["status"], "awaiting_approval")
        self.assertEqual(costlog.read_log(self.p), [])

    def test_bad_input_is_a_clean_client_error(self):
        r = self.c.post(self.url, json={"inputs": {"product": "../../x.png", "setting": "studio"}}, headers=self.S)
        self.assertGreaterEqual(r.status_code, 400)
        self.assertLess(r.status_code, 500)
        self.assertEqual(self.c.post("/api/projects/demo/recipes/nope/plan", json={}, headers=self.S).status_code // 100, 4)


class TestRecipeTools(unittest.TestCase):
    def setUp(self):
        HERM.all_test(self)
        self.home = tempfile.mkdtemp()
        os.environ["AISTUDIO_HOME"] = self.home
        self.ws = Workspace(self.home)
        self.ws.create_project("demo", test_pipeline=True)
        (self.ws.pdir("demo") / "stills").mkdir(exist_ok=True)
        (self.ws.pdir("demo") / "stills" / "product.png").write_bytes(PNG)
        HERM.register_test_media(self.ws.pdir("demo"), "stills/product.png")

    def test_crew_can_list_but_never_plan_approve_or_run(self):
        self.assertEqual(R.cost_class("list_recipes"), "free")
        self.assertEqual(R.cost_class("plan_recipe"), "human_only")
        crew = set(R.crew_tools())
        self.assertIn("list_recipes", crew)
        for n in ("plan_recipe", "approve_batch", "run_batch"):
            self.assertNotIn(n, crew)

    def test_mcp_plan_creates_only_an_awaiting_batch(self):
        listed = R.TOOLS["list_recipes"][2](self.ws, {"name": "demo"})["recipes"]
        self.assertTrue(any(r["id"] == "product-ad-9x16" and r["available"] for r in listed))
        b = R.TOOLS["plan_recipe"][2](self.ws, {"name": "demo", "recipe": "product-ad-9x16", "inputs": BODY["inputs"]})
        self.assertEqual((b["status"], b["actor"]), ("awaiting_approval", "mcp"))
        self.assertEqual(costlog.read_log(self.ws.pdir("demo")), [])

    def test_cli_list_and_plan_json(self):
        lines = []
        self.assertEqual(cli.main(["recipe", "list", "--json"], out=lines.append), 0)
        self.assertTrue(any(r["id"] == "headshot" and not r["available"] for r in json.loads("".join(lines))))
        lines.clear()
        args = ["recipe", "plan", "demo", "product-placement", "--input", "product=stills/product.png", "--input", "setting=studio", "--json"]
        self.assertEqual(cli.main(args, out=lines.append), 0)
        self.assertEqual(json.loads("".join(lines))["status"], "awaiting_approval")


if __name__ == "__main__":
    unittest.main()
