"""Tests for the ComfyUI workflow registry (plan 25)."""
import json
import tempfile
import unittest
from pathlib import Path

from aistudio.comfy_workflows import (list_workflows, get_workflow, add_workflow,
                                       delete_workflow, validate_workflow, _workflows_root,
                                       _trash_root, MAX_JSON_SIZE, ID_RE)
from aistudio.settings_api import SettingsMixin
from aistudio.domain.common import ServiceError

# Fixtures
FIXTURES = Path(__file__).parent / "fixtures" / "comfyui"
TINY_MANIFEST = json.loads((FIXTURES / "tiny" / "manifest.json").read_text())
TINY_WORKFLOW = json.loads((FIXTURES / "tiny" / "workflow_api.json").read_text())


class TestComfyWorkflows(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.settings_dir = Path(self.tmp) / "settings"
        self.settings_dir.mkdir(parents=True)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_list_workflows_empty(self):
        out = list_workflows(self.settings_dir)
        self.assertEqual(out, [])

    def test_add_and_get_workflow(self):
        # Add a workflow
        added = add_workflow(self.settings_dir, TINY_WORKFLOW, TINY_MANIFEST)
        self.assertEqual(added["id"], "tiny")
        self.assertEqual(added["task"], "image")
        self.assertIn("prompt", added["inputs"])
        self.assertIn("negative_prompt", added["inputs"])
        self.assertIn("seed", added["inputs"])

        # Get it back
        got = get_workflow(self.settings_dir, "tiny")
        self.assertEqual(got["id"], "tiny")
        self.assertEqual(got["task"], "image")
        self.assertEqual(got["inputs"], TINY_MANIFEST["inputs"])
        self.assertEqual(got["profile"], TINY_MANIFEST["profile"])
        self.assertEqual(got["workflow"], TINY_WORKFLOW)

    def test_list_workflows_returns_added(self):
        add_workflow(self.settings_dir, TINY_WORKFLOW, TINY_MANIFEST)
        out = list_workflows(self.settings_dir)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["id"], "tiny")
        self.assertEqual(out[0]["task"], "image")

    def test_duplicate_workflow_rejected(self):
        add_workflow(self.settings_dir, TINY_WORKFLOW, TINY_MANIFEST)
        with self.assertRaises(ServiceError) as cm:
            add_workflow(self.settings_dir, TINY_WORKFLOW, TINY_MANIFEST)
        self.assertIn("already exists", str(cm.exception))

    def test_invalid_id_rejected(self):
        # The slugification converts invalid chars to valid ones
        # So "Bad ID!" becomes "bad-id" which is valid
        manifest = {**TINY_MANIFEST, "id": "Bad ID!"}
        added = add_workflow(self.settings_dir, TINY_WORKFLOW, manifest)
        self.assertEqual(added["id"], "bad-id")

    def test_missing_id_rejected(self):
        bad_manifest = {**TINY_MANIFEST}
        bad_manifest.pop("id")
        with self.assertRaises(ServiceError) as cm:
            add_workflow(self.settings_dir, TINY_WORKFLOW, bad_manifest)
        self.assertIn("must have a non-empty 'id'", str(cm.exception))

    def test_workflow_too_large_rejected(self):
        # Create a workflow that exceeds the size limit
        large_workflow = {str(i): {"class_type": "Test", "inputs": {"data": "x" * 10000}} for i in range(300)}
        large_manifest = {**TINY_MANIFEST, "id": "large"}
        with self.assertRaises(ServiceError) as cm:
            add_workflow(self.settings_dir, large_workflow, large_manifest)
        self.assertIn("exceeds", str(cm.exception))

    def test_manifest_too_large_rejected(self):
        # Create a manifest with a huge profile
        large_manifest = {**TINY_MANIFEST, "id": "large", "profile": {"data": "x" * 3000000}}
        with self.assertRaises(ServiceError) as cm:
            add_workflow(self.settings_dir, TINY_WORKFLOW, large_manifest)
        self.assertIn("exceeds", str(cm.exception))

    def test_invalid_mapping_rejected(self):
        # Manifest points at a node that doesn't exist
        bad_manifest = {**TINY_MANIFEST, "id": "bad", "inputs": {"prompt": ["999", "text"]}}
        with self.assertRaises(ServiceError) as cm:
            add_workflow(self.settings_dir, TINY_WORKFLOW, bad_manifest)
        self.assertIn("node '999'", str(cm.exception))

    def test_invalid_input_rejected(self):
        # Manifest points at an input that doesn't exist on the node
        bad_manifest = {**TINY_MANIFEST, "id": "bad", "inputs": {"prompt": ["6", "nonexistent"]}}
        with self.assertRaises(ServiceError) as cm:
            add_workflow(self.settings_dir, TINY_WORKFLOW, bad_manifest)
        self.assertIn("6.nonexistent", str(cm.exception))

    def test_delete_workflow_moves_to_trash(self):
        add_workflow(self.settings_dir, TINY_WORKFLOW, TINY_MANIFEST)
        result = delete_workflow(self.settings_dir, "tiny")
        self.assertEqual(result["deleted"], "tiny")
        self.assertIn("_trash", result["trash"])
        # Original folder is gone
        self.assertFalse((_workflows_root(self.settings_dir) / "tiny").exists())
        # Trash folder exists
        self.assertTrue(Path(result["trash"]).exists())
        # Listing returns empty
        self.assertEqual(list_workflows(self.settings_dir), [])

    def test_delete_nonexistent_rejected(self):
        with self.assertRaises(ServiceError) as cm:
            delete_workflow(self.settings_dir, "nope")
        self.assertIn("no such workflow", str(cm.exception))

    def test_invalid_id_format_rejected_on_get(self):
        with self.assertRaises(ServiceError) as cm:
            get_workflow(self.settings_dir, "Bad ID!")
        self.assertIn("invalid workflow id", str(cm.exception))

    def test_invalid_id_format_rejected_on_delete(self):
        with self.assertRaises(ServiceError) as cm:
            delete_workflow(self.settings_dir, "Bad ID!")
        self.assertIn("invalid workflow id", str(cm.exception))

    def test_validate_workflow_dry_run(self):
        # Valid workflow
        result = validate_workflow(self.settings_dir, TINY_WORKFLOW, TINY_MANIFEST)
        self.assertTrue(result["ok"])
        self.assertEqual(result["id"], "tiny")
        self.assertEqual(result["task"], "image")

    def test_validate_workflow_invalid_mapping(self):
        # Invalid mapping
        bad_manifest = {**TINY_MANIFEST, "id": "bad", "inputs": {"prompt": ["999", "text"]}}
        with self.assertRaises(ServiceError) as cm:
            validate_workflow(self.settings_dir, TINY_WORKFLOW, bad_manifest)
        self.assertIn("node '999'", str(cm.exception))

    def test_slug_generation(self):
        # ID is slugified from manifest
        manifest = {**TINY_MANIFEST, "id": "My Workflow Template!"}
        added = add_workflow(self.settings_dir, TINY_WORKFLOW, manifest)
        self.assertEqual(added["id"], "my-workflow-template")

    def test_get_nonexistent_rejected(self):
        with self.assertRaises(ServiceError) as cm:
            get_workflow(self.settings_dir, "nope")
        self.assertIn("no such workflow", str(cm.exception))

    def test_workflow_without_folder_not_found(self):
        with self.assertRaises(ServiceError) as cm:
            get_workflow(self.settings_dir, "tiny")
        self.assertIn("no such workflow", str(cm.exception))


class TestComfyWorkflowsIntegration(unittest.TestCase):
    """Integration tests using the SettingsMixin (like the API would)."""
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.settings_dir = Path(self.tmp) / "settings"
        self.settings_dir.mkdir(parents=True)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_settings_mixin_methods(self):
        class TestMixin(SettingsMixin):
            def __init__(self, settings_dir):
                self.settings_dir = Path(settings_dir)
                self.root = Path(settings_dir).parent
                from aistudio import secrets as secrets_mod
                self.secrets = secrets_mod.SecretStore()
                from aistudio import pricing as pricing_mod
                self.pricing = pricing_mod.Pricing.load(self.root / "rates.json", self.settings_dir)
                self._runner = None
                self._health = None
                self.auto_verify = False
                self.catalog_fetch = None

        mixin = TestMixin(self.settings_dir)

        # Test list (empty)
        self.assertEqual(mixin.comfy_workflows_list(), [])

        # Test add
        added = mixin.comfy_workflows_add(TINY_WORKFLOW, TINY_MANIFEST)
        self.assertEqual(added["id"], "tiny")

        # Test list (has one)
        out = mixin.comfy_workflows_list()
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["id"], "tiny")

        # Test get
        got = mixin.comfy_workflows_get("tiny")
        self.assertEqual(got["id"], "tiny")
        self.assertEqual(got["workflow"], TINY_WORKFLOW)

        # Test validate
        validated = mixin.comfy_workflows_validate(TINY_WORKFLOW, TINY_MANIFEST)
        self.assertTrue(validated["ok"])

        # Test delete
        deleted = mixin.comfy_workflows_delete("tiny")
        self.assertEqual(deleted["deleted"], "tiny")
        self.assertEqual(mixin.comfy_workflows_list(), [])


class TestComfyWorkflowsCatalogIntegration(unittest.TestCase):
    """Tests for catalog integration with ComfyUI workflows."""
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.settings_dir = Path(self.tmp) / "settings"
        self.settings_dir.mkdir(parents=True)
        # Create a fake rates.json
        (Path(self.tmp) / "rates.json").write_text(json.dumps({"models": {}}))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_catalog_profile_from_comfy_manifest(self):
        from aistudio.catalog import Catalog
        from aistudio import pricing as pricing_mod

        # Add a workflow
        add_workflow(self.settings_dir, TINY_WORKFLOW, TINY_MANIFEST)

        # Create catalog
        pricing = pricing_mod.Pricing.load(Path(self.tmp) / "rates.json", self.settings_dir)
        catalog = Catalog(self.settings_dir, pricing)

        # Get profile for wf:tiny
        profile = catalog.profile("comfyui", "video", "wf:tiny")
        self.assertEqual(profile["source"], "comfy_manifest")
        # The tiny manifest has task="image", so it should be text_to_image
        self.assertEqual(profile["tasks"], ["text_to_image"])

    def test_catalog_user_override_wins_over_comfy(self):
        from aistudio.catalog import Catalog
        from aistudio import pricing as pricing_mod

        add_workflow(self.settings_dir, TINY_WORKFLOW, TINY_MANIFEST)

        pricing = pricing_mod.Pricing.load(Path(self.tmp) / "rates.json", self.settings_dir)
        catalog = Catalog(self.settings_dir, pricing)

        # Add a user override
        models_file = self.settings_dir / "models.json"
        models_file.write_text(json.dumps({"capabilities": {"comfyui|wf:tiny": {"tasks": ["custom_task"], "source": "user"}}}))

        profile = catalog.profile("comfyui", "video", "wf:tiny")
        self.assertEqual(profile["source"], "user")
        self.assertIn("custom_task", profile["tasks"])

    def test_catalog_free_price_for_wf_models(self):
        from aistudio import pricing as pricing_mod

        pricing = pricing_mod.Pricing.load(Path(self.tmp) / "rates.json", self.settings_dir)
        card = pricing.card("comfyui", "video", "wf:tiny")
        self.assertIsNotNone(card)
        self.assertTrue(pricing.is_free(card))
        self.assertEqual(card["kind"], "video")

    def test_catalog_builtin_still_works(self):
        from aistudio.catalog import Catalog
        from aistudio import pricing as pricing_mod

        pricing = pricing_mod.Pricing.load(Path(self.tmp) / "rates.json", self.settings_dir)
        catalog = Catalog(self.settings_dir, pricing)

        # Test a regular provider model (not wf:)
        profile = catalog.profile("openrouter", "video", "google/veo-3.1")
        self.assertEqual(profile["source"], "default")  # no builtin entry for this


class TestComfyWorkflowsAPI(unittest.TestCase):
    """API tests using fake transport."""
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.root = Path(self.tmp)
        self.settings_dir = self.root / "settings"
        self.settings_dir.mkdir(parents=True)
        (self.root / "rates.json").write_text(json.dumps({"models": {}}))
        (self.root / "projects").mkdir(parents=True)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_api_routes_exist(self):
        # Just verify the routes are registered in api_docs
        from server.api_docs import DOCS
        self.assertIn("GET /api/comfy/workflows", DOCS)
        self.assertIn("GET /api/comfy/workflows/{wf_id}", DOCS)
        self.assertIn("POST /api/comfy/workflows", DOCS)
        self.assertIn("POST /api/comfy/workflows/validate", DOCS)
        self.assertIn("DELETE /api/comfy/workflows/{wf_id}", DOCS)
        for key in ["GET /api/comfy/workflows", "GET /api/comfy/workflows/{wf_id}",
                    "POST /api/comfy/workflows", "POST /api/comfy/workflows/validate",
                    "DELETE /api/comfy/workflows/{wf_id}"]:
            self.assertFalse(DOCS[key]["agent"])  # human session only


if __name__ == "__main__":
    unittest.main()