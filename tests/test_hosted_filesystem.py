import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from aistudio import approvals, context, project_lock
from aistudio.domain.common import ServiceError
from aistudio.service import Workspace


class HostedFilesystemTests(unittest.TestCase):
    def setUp(self):
        from tests import _hermetic  # noqa: F401
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.hosted = patch.dict(os.environ, {"AISTUDIO_HOSTED": "1"})
        self.hosted.start()
        self.addCleanup(self.hosted.stop)
        self.ws = Workspace(self.root)

    def tenant(self, tenant_id):
        return context.use_context(context.RequestContext(tenant_id, actor="human", role="owner"))

    def test_same_project_name_is_partitioned_for_files_approvals_and_spend(self):
        with self.tenant("tenant_a"):
            self.ws.create_project("shared")
            self.ws.put_text("shared", "Story.md", "tenant A")
            path_a = self.ws.pdir("shared")
            proposal = approvals.propose(path_a, "image", "shot", "fake", 1, {"text": "A"}, reveal_code=True)
            project_lock.reserve(path_a, proposal["id"], 1, actor="human")

        with self.tenant("tenant_b"):
            with self.assertRaises(ServiceError):
                self.ws.get_text("shared", "Story.md")
            self.ws.create_project("shared")
            self.ws.put_text("shared", "Story.md", "tenant B")
            path_b = self.ws.pdir("shared")
            self.assertEqual(self.ws.get_text("shared", "Story.md"), "tenant B")
            self.assertFalse((path_b / "proposals.json").exists())
            self.assertEqual(project_lock.reserved(path_b), 0)
            with self.assertRaises(approvals.ApprovalError):
                approvals.get(path_b, proposal["id"])
            self.assertNotEqual((path_a / ".spend.lock").resolve(), (path_b / ".spend.lock").resolve())

        self.assertEqual(path_a, self.root / "tenants" / "tenant_a" / "projects" / "shared")
        self.assertEqual(path_b, self.root / "tenants" / "tenant_b" / "projects" / "shared")

    def test_local_layout_remains_unchanged(self):
        with patch.dict(os.environ, {"AISTUDIO_HOSTED": "0"}):
            local = Workspace(self.root / "local")
            local.create_project("shared")
            self.assertEqual(local.project_root, self.root / "local")
            self.assertTrue((self.root / "local" / "projects" / "shared").is_dir())
            self.assertFalse((self.root / "local" / "tenants").exists())

    def test_invalid_and_symlink_tenant_roots_are_rejected(self):
        for tenant_id in ("..", "../escape", "a/b", "local"):
            with self.subTest(tenant_id=tenant_id), self.tenant(tenant_id):
                with self.assertRaises(RuntimeError):
                    self.ws.project_root

        tenants = self.root / "tenants"
        tenants.mkdir()
        external = self.root / "external"
        external.mkdir()
        (tenants / "linked").symlink_to(external, target_is_directory=True)
        with self.tenant("linked"):
            with self.assertRaises(RuntimeError):
                self.ws.project_root

    def test_tenant_partition_root_cannot_be_a_symlink(self):
        external = self.root / "external"
        external.mkdir()
        (self.root / "tenants").symlink_to(external, target_is_directory=True)
        with self.tenant("tenant_a"):
            with self.assertRaises(RuntimeError):
                self.ws.project_root
