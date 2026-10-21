import tempfile
import unittest

from aistudio import context, jobs, library, store
from aistudio.costlog import append_log, read_log
from aistudio.secrets import SecretStore
from aistudio.tenancy import Org, Role, SpendPolicy, Workspace, can, evaluate


class TenancyTests(unittest.TestCase):
    def tearDown(self):
        store.close_all()

    def test_rbac_and_spend_policy(self):
        self.assertTrue(can(Role.ORG_ADMIN, "approve_spend"))
        self.assertFalse(can(Role.WORKSPACE_REVIEWER, "approve_spend"))
        self.assertTrue(can(Role.WORKSPACE_REVIEWER, "comment"))
        self.assertEqual(evaluate(SpendPolicy(approval_threshold_usd=5, allow_autopilot=True), Role.WORKSPACE_EDITOR, 4), "allow")
        self.assertEqual(evaluate(SpendPolicy(approval_threshold_usd=5), Role.WORKSPACE_EDITOR, 8), "needs_admin")
        self.assertEqual(evaluate(SpendPolicy(monthly_cap_usd=10), Role.ORG_ADMIN, 11), "deny")
        self.assertIsInstance(Org("acme", "Acme"), Org)
        self.assertIsInstance(Workspace("w1", "acme", "Design"), Workspace)

    def test_context_stamps_writers_and_defaults_to_local(self):
        root = tempfile.mkdtemp()
        ctx = context.RequestContext("org-7", "user-3", Role.WORKSPACE_EDITOR)
        with context.use_context(ctx):
            job = jobs.enqueue(root, "demo", "export")
            self.assertEqual((job["tenant_id"], job["actor"]), ("org-7", "user-3"))
            item = library._upsert(root, dict(project="demo", kind="image", category="image", file="stills/a.png", sha="x",
                                              prompt="", model="", provider="", seed="", cost=0, status="completed", created=1))
            self.assertEqual((item["tenant_id"], item["actor"]), ("org-7", "user-3"))
            append_log(root, {"shot": "s1", "stage": "image", "attempt": "1"})
            self.assertEqual((read_log(root)[0]["tenant_id"], read_log(root)[0]["actor"]), ("org-7", "user-3"))
        local_job = jobs.enqueue(root, "demo", "export")
        self.assertEqual((local_job["tenant_id"], local_job["actor"]), ("local", "local"))
        self.assertEqual((store.current_tenant(), store.current_actor()), ("local", "local"))
        local_item = library._upsert(root, dict(project="demo", kind="image", category="image", file="stills/local.png", sha="local",
                                                prompt="", model="", provider="", seed="", cost=0, status="completed", created=1))
        self.assertEqual((local_item["tenant_id"], local_item["actor"]), ("local", "local"))
        with context.use_context(ctx):
            self.assertIsNone(jobs.get(root, local_job["id"]))
            self.assertIsNone(library.get(root, local_item["id"]))

    def test_secret_namespace_isolated_and_local_compatible(self):
        directory = tempfile.mkdtemp()
        secrets = SecretStore(directory, keyring_mod=None)
        secrets.set("provider", {"api_key": "local-secret"})
        secrets.set("provider", {"api_key": "tenant-secret"}, namespace="org-7")
        self.assertEqual(secrets.get("provider"), {"api_key": "local-secret"})
        self.assertEqual(secrets.get("provider", namespace="org-7"), {"api_key": "tenant-secret"})
        with context.use_context(context.RequestContext("org-7", "user-3", Role.ORG_ADMIN)):
            self.assertEqual(secrets.get("provider"), {"api_key": "tenant-secret"})

    def test_job_worker_restores_submitting_context(self):
        import threading
        root = tempfile.mkdtemp()
        finished = threading.Event()
        observed = []
        runner = jobs.JobRunner(root, {"export": lambda job, progress: observed.append((store.current_tenant(), store.current_actor())) or finished.set() or {}})
        try:
            with context.use_context(context.RequestContext("org-7", "user-3", Role.WORKSPACE_EDITOR)):
                submitted = runner.submit("demo", "export")
                self.assertEqual((submitted["tenant_id"], submitted["actor"]), ("org-7", "user-3"))
            self.assertTrue(finished.wait(5))
            self.assertEqual(observed, [("org-7", "user-3")])
        finally:
            runner.shutdown()


if __name__ == "__main__":
    unittest.main()
