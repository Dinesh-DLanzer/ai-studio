import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import tests._hermetic as HERM
from aistudio import context, costlog, library, store
from aistudio.tenancy import Role


class TestHardeningTenancy(unittest.TestCase):
    def setUp(self):
        HERM.all_test(self)
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        store.close_all()
        self.tmp.cleanup()

    def test_hosted_mode_fails_closed(self):
        with patch.dict(os.environ, {"AISTUDIO_HOSTED": "1"}):
            # 1. Unset context raises RuntimeError
            with self.assertRaises(RuntimeError):
                context.get_context()

            # 2. Context with tenant_id="local" or default raises RuntimeError
            with context.use_context(context.RequestContext()):
                with self.assertRaises(RuntimeError):
                    context.get_context()

            with context.use_context(context.RequestContext(tenant_id="local", actor="u1", role=Role.WORKSPACE_EDITOR)):
                with self.assertRaises(RuntimeError):
                    context.get_context()

            # 3. Context with role="org_owner" raises RuntimeError outside local mode
            with context.use_context(context.RequestContext(tenant_id="org-acme", actor="u1", role="org_owner")):
                with self.assertRaises(RuntimeError):
                    context.get_context()

            # 4. Explicit non-local tenant and valid hosted role succeeds
            ctx = context.RequestContext(tenant_id="org-acme", actor="u1", role=Role.WORKSPACE_EDITOR)
            with context.use_context(ctx):
                self.assertEqual(context.get_context(), ctx)

    def test_verify_threads_inherit_context(self):
        from aistudio.domain.verify import VerifyDomain

        observed_contexts = []
        ctx = context.RequestContext(tenant_id="org-special", actor="user-agent", role=Role.WORKSPACE_EDITOR)

        class FakeWS:
            auto_verify = True
            _verify_lock = threading.Lock()
            _verify_running = set()
            def pdir(self, name): return Path(tempfile.mkdtemp())

        domain = VerifyDomain(FakeWS())

        # Spy on verify_run to observe context in background thread
        done = threading.Event()
        def fake_verify_run(name, scope, ai=True):
            observed_contexts.append(context.get_context())
            done.set()

        domain.verify_run = fake_verify_run

        with context.use_context(ctx):
            domain.verify_now("test_proj", "story")

        self.assertTrue(done.wait(5))
        self.assertEqual(len(observed_contexts), 1)
        self.assertEqual(observed_contexts[0].tenant_id, "org-special")
        self.assertEqual(observed_contexts[0].actor, "user-agent")

    def test_library_fts_wipe_scoped_to_tenant(self):
        # Insert items for tenant-a
        ctx_a = context.RequestContext("tenant-a", "user-a", Role.WORKSPACE_EDITOR)
        with context.use_context(ctx_a):
            item_a = library._upsert(self.root, dict(
                project="proj_a", kind="image", category="image", file="stills/a.png", sha="sha_a",
                prompt="unique prompt for alpha", model="m1", provider="p1", seed="", cost=0, status="completed", created=1
            ))

        # Insert items for tenant-b
        ctx_b = context.RequestContext("tenant-b", "user-b", Role.WORKSPACE_EDITOR)
        with context.use_context(ctx_b):
            item_b = library._upsert(self.root, dict(
                project="proj_b", kind="image", category="image", file="stills/b.png", sha="sha_b",
                prompt="unique prompt for beta", model="m1", provider="p1", seed="", cost=0, status="completed", created=1
            ))

        # Both can be searched in FTS
        with context.use_context(ctx_a):
            res_a = library.search(self.root, q="alpha")
            self.assertEqual(len(res_a["items"]), 1)
            self.assertEqual(res_a["items"][0]["id"], item_a["id"])

        with context.use_context(ctx_b):
            res_b = library.search(self.root, q="beta")
            self.assertEqual(len(res_b["items"]), 1)
            self.assertEqual(res_b["items"][0]["id"], item_b["id"])

        # Wipe FTS for tenant-a
        with context.use_context(ctx_a):
            library.wipe_fts(self.root, tenant_id="tenant-a")

        # Tenant-b's items in FTS must still be intact!
        with context.use_context(ctx_b):
            res_b2 = library.search(self.root, q="beta")
            self.assertEqual(len(res_b2["items"]), 1)
            self.assertEqual(res_b2["items"][0]["id"], item_b["id"])

    def test_costlog_reads_and_spent_filter_by_tenant(self):
        pdir = self.root / "projects" / "p1"
        pdir.mkdir(parents=True)

        ctx_1 = context.RequestContext("tenant-1", "user-1", Role.WORKSPACE_EDITOR)
        with context.use_context(ctx_1):
            costlog.append_log(pdir, {"shot": "s1", "stage": "clip", "attempt": "1", "cost": "1.50"})

        ctx_2 = context.RequestContext("tenant-2", "user-2", Role.WORKSPACE_EDITOR)
        with context.use_context(ctx_2):
            costlog.append_log(pdir, {"shot": "s2", "stage": "clip", "attempt": "1", "cost": "2.75"})

        # Under tenant-1: only see s1 ($1.50)
        with context.use_context(ctx_1):
            rows_1 = costlog.read_log(pdir)
            self.assertEqual(len(rows_1), 1)
            self.assertEqual(rows_1[0]["shot"], "s1")
            self.assertAlmostEqual(costlog.spent(pdir), 1.50)
            self.assertAlmostEqual(costlog.split(pdir)["total"], 1.50)

        # Under tenant-2: only see s2 ($2.75)
        with context.use_context(ctx_2):
            rows_2 = costlog.read_log(pdir)
            self.assertEqual(len(rows_2), 1)
            self.assertEqual(rows_2[0]["shot"], "s2")
            self.assertAlmostEqual(costlog.spent(pdir), 2.75)
            self.assertAlmostEqual(costlog.split(pdir)["total"], 2.75)


if __name__ == "__main__":
    unittest.main()
