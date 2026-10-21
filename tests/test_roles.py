import tests._hermetic as HERM  # noqa: F401  (no real key or network in tests)
import tempfile
import unittest
from pathlib import Path
from aistudio import approvals, roles as R
from aistudio.pricing import Pricing, key
from aistudio.providers import config as C
from aistudio.providers.base import Adapter, AuthError, Rejected, Retryable
from aistudio.secrets import SecretStore


class Script(Adapter):
    """Adapter whose behaviour per model is scripted: a list of outcomes (exception => raise, else return)."""
    capabilities = frozenset({"chat", "vision", "image", "video"})
    log = []

    def __init__(self, conn, plan):
        super().__init__(conn, transport=lambda *a, **k: {})
        self.plan = plan

    def _next(self, model, what):
        Script.log.append((self.conn["id"], model, what))
        steps = self.plan.get(model, ["ok"])
        s = steps.pop(0) if len(steps) > 1 else steps[0]
        if isinstance(s, Exception):
            raise s
        return s

    def chat(self, model, messages, opts=None):
        s = self._next(model, "chat")
        return {"text": f"hi from {model}", "usage": {"input": 1000, "output": 1000}, "cost": None, "model": model}

    def image(self, model, prompt, refs=(), aspect_ratio="9:16", opts=None):
        self._next(model, "image")
        return {"bytes": b"PNG", "usage": {}, "cost": None, "model": model}

    def vision(self, model, prompt, images, opts=None):
        self._next(model, "vision")
        return {"text": "ok", "usage": {}, "cost": None, "model": model}

    def video_submit(self, model, req):
        self._next(model, "submit")
        return {"job_id": "J-" + model, "model": model}

    def video_poll(self, job):
        s = self.plan.get("poll:" + job["model"], [{"status": "done", "error": None, "cost": None}])
        s = s.pop(0) if len(s) > 1 else s[0]
        if isinstance(s, Exception):
            raise s
        return s

    def video_download(self, job):
        return b"MP4"


def setup(plan=None, chains=None, providers=None, secrets=("g", "o", "k", "r"), mode_fake=False, overrides=None):
    d = Path(tempfile.mkdtemp())
    provs = providers or [{"id": i, "type": t, "label": i.upper(), "base_url": "", "enabled": True}
                          for i, t in (("g", "google"), ("o", "openai"), ("k", "kling"), ("r", "runway"))]
    C.save_providers(d, provs)
    doc = C.default_roles()
    for role, chain in (chains or {}).items():
        doc["roles"][role]["chain"] = chain
    C.save_roles(d, doc, provs)
    sec = SecretStore(d / "sec")
    for s in secrets:
        sec.set(s, {"api_key": "key-" + s + "-123456"})
    plan = plan or {}
    pr = Pricing({}, {key("g", "veo"): {"kind": "video", "per_second": {"720p": 0.05}}, key("k", "kling-v1"): {"kind": "video", "per_second": {"720p": 0.02}},
                      key("r", "veo2"): {"kind": "video", "per_second": {"720p": 0.5}},
                      key("g", "gem"): {"kind": "text", "input_per_1m": 1.0, "output_per_1m": 3.0}, key("o", "gpt"): {"kind": "text", "free": True},
                      key("g", "img"): {"kind": "image", "per_image": 0.04}})
    Script.log = []
    sleeps = []
    r = R.RoleRunner(d, sec, pr, adapter_factory=lambda p: Script({"id": p["id"], "type": p["type"], "secret": {"api_key": "key-" + p["id"] + "-123456"}}, plan.setdefault(p["id"], {})),
                     fake_mode=lambda: mode_fake, sleep=sleeps.append, poll_seconds=0)
    r.sleeps = sleeps
    return r, d


def ch(*pairs):
    return [{"provider": p, "model": m} for p, m in pairs]


class TestChain(unittest.TestCase):
    def test_first_model_wins_and_cost_computed(self):
        r, _ = setup(chains={"chat": ch(("g", "gem"), ("o", "gpt"))})
        out = r.chat("chat", [])
        self.assertEqual((out["provider"], out["model"], out["cost_source"]), ("g", "gem", "computed"))
        self.assertEqual(out["cost"], 0.004)
        self.assertEqual(len(Script.log), 1)

    def test_unconfigured(self):
        r, _ = setup()
        with self.assertRaises(R.ChainError) as c:
            r.chat("chat", [])
        self.assertEqual(c.exception.code, "unconfigured")

    def test_retry_then_fallback_with_backoff(self):
        r, _ = setup({"g": {"gem": [Retryable("HTTP 429"), Retryable("HTTP 429")]}}, {"chat": ch(("g", "gem"), ("o", "gpt"))})
        out = r.chat("chat", [])
        self.assertEqual(out["provider"], "o")
        self.assertEqual([a[0] for a in Script.log], ["g", "g", "o"])           # 1 try + 1 retry, then the next model
        self.assertEqual(r.sleeps, [1])
        self.assertEqual(out["cost"], 0.0)                                       # free model
        self.assertEqual(len(out["attempts"]), 2)

    def test_retry_then_success_on_same_model(self):
        r, _ = setup({"g": {"gem": [Retryable("HTTP 500"), "ok"]}}, {"chat": ch(("g", "gem"), ("o", "gpt"))})
        self.assertEqual(r.chat("chat", [])["provider"], "g")

    def test_auth_marks_unhealthy_and_is_skipped_next_time(self):
        r, _ = setup({"g": {"gem": [AuthError("HTTP 401 key-g-123456")]}}, {"chat": ch(("g", "gem"), ("o", "gpt"))})
        out = r.chat("chat", [])
        self.assertEqual(out["provider"], "o")
        self.assertNotIn("key-g-123456", str(out["attempts"]))
        self.assertTrue(r.health.unhealthy("g"))
        Script.log.clear()
        r.chat("chat", [])
        self.assertEqual([a[0] for a in Script.log], ["o"])

    def test_rejected_goes_next_without_retry(self):
        r, _ = setup({"g": {"gem": [Rejected("HTTP 400 blocked")]}}, {"chat": ch(("g", "gem"), ("o", "gpt"))})
        r.chat("chat", [])
        self.assertEqual([a[0] for a in Script.log], ["g", "o"])

    def test_all_fail_message_lists_every_attempt(self):
        r, _ = setup({"g": {"gem": [Rejected("nope A")]}, "o": {"gpt": [Rejected("nope B")]}}, {"chat": ch(("g", "gem"), ("o", "gpt"))})
        with self.assertRaises(R.ChainError) as c:
            r.chat("chat", [])
        self.assertIn("nope A", str(c.exception))
        self.assertIn("nope B", str(c.exception))

    def test_problem_entries_are_skipped(self):
        r, d = setup(chains={"chat": ch(("g", "gem"), ("o", "gpt"))}, secrets=("o",))
        self.assertEqual(r.chat("chat", [])["provider"], "o")                    # g has no key
        self.assertEqual(r.resolve("chat")[0]["problem"], "no API key")

    def test_allow_filter_blocks_paid(self):
        r, _ = setup(chains={"chat": ch(("g", "gem"), ("o", "gpt"))})
        out = r.chat("chat", [], allow=lambda e: (r.pricing.is_free(e["card"]), "paid model not allowed"))
        self.assertEqual(out["provider"], "o")

    def test_fake_mode_ignores_chain(self):
        r, _ = setup(mode_fake=True)
        r.factory = None
        out = r.chat("chat", [{"role": "user", "content": "yo"}])
        self.assertEqual((out["provider"], out["text"]), ("fake", "FAKE: yo"))
        with self.assertRaises(R.GrantRequired):
            r.image("p")

    def test_project_override(self):
        r, d = setup(chains={"chat": ch(("g", "gem"))})
        proj = Path(tempfile.mkdtemp())
        (proj / "roles.override.json").write_text('{"roles":{"chat":{"chain":[{"provider":"o","model":"gpt"}]}}}')
        self.assertEqual(r.chat("chat", [], project_dir=proj)["provider"], "o")


class TestPaid(unittest.TestCase):
    REQ = {"prompt": "p", "seconds": 4, "resolution": "720p", "aspect_ratio": "9:16", "audio": False}

    @staticmethod
    def grant(p, kind, price, model="model", provider="g"):
        prop = approvals.propose(p, kind, "target", model, price, {"prompt": "p", "provider": provider},
                                 reveal_code=True, summary={"provider": provider})
        approvals.approve(p, prop["id"], prop["code"])
        return approvals.consume(p, prop["id"], prop["hash"])

    def test_image_requires_grant(self):
        r, _ = setup(chains={"image": ch(("g", "img"))})
        with self.assertRaises(R.GrantRequired):
            r.image("p")

    def test_vision_requires_grant(self):
        r, p = setup(chains={"vision": ch(("g", "gem"))})
        with self.assertRaises(R.GrantRequired):
            r.vision("review", [], project_dir=p)

    def test_token_priced_vision_requires_allow_paid_and_logs_unknown_cost(self):
        r, p = setup(chains={"vision": ch(("g", "token-vision"))})
        r.pricing.overrides[key("g", "token-vision")] = {"kind": "text", "input_per_1m": 1.0, "output_per_1m": 2.0}
        grant = self.grant(p, "review", 0.003, model="token-vision")
        with self.assertRaises(R.ChainError):
            r.vision("review", [], project_dir=p, grant=grant)
        self.assertEqual(Script.log, [])
        grant = self.grant(p, "review", 0.003, model="token-vision")
        out = r.vision("review", [], project_dir=p, grant=grant, allow_paid=True)
        self.assertEqual(out["cost_source"], "unknown")

    def test_unknown_vision_primary_can_run_with_its_approval(self):
        r, p = setup(chains={"vision": ch(("g", "unknown"))})
        out = r.vision("review", [], project_dir=p,
                       grant=self.grant(p, "review", 0.003, model="unknown"), allow_paid=True)
        self.assertEqual(out["cost_source"], "unknown")
        self.assertEqual(Script.log, [("g", "unknown", "vision")])

    def test_vision_fallback_needs_approval_for_unknown_or_dearer_price(self):
        for card, price in ((None, None),
                            ({"kind": "text", "input_per_1m": 1.0, "output_per_1m": 2.0}, None),
                            ({"kind": "text", "per_call": 0.004}, 0.004)):
            with self.subTest(card=card):
                r, p = setup({"g": {"primary": [Rejected("blocked")]}},
                             {"vision": ch(("g", "primary"), ("o", "fallback"))})
                r.pricing.overrides[key("g", "primary")] = {"kind": "text", "per_call": 0.003}
                if card:
                    r.pricing.overrides[key("o", "fallback")] = card
                with self.assertRaises(R.NeedsNewApproval) as c:
                    r.vision("review", [], project_dir=p,
                             grant=self.grant(p, "review", 0.003, model="primary"), allow_paid=True)
                self.assertEqual(c.exception.entry["model"], "fallback")
                self.assertEqual(c.exception.price, price)
                self.assertEqual(c.exception.code, "needs_approval")
                self.assertEqual(Script.log, [("g", "primary", "vision")])

    def test_unknown_vision_exception_does_not_cover_another_fallback(self):
        r, p = setup({"g": {"primary": [Rejected("blocked")]}},
                     {"vision": ch(("g", "primary"), ("g", "fallback"))})
        with self.assertRaises(R.NeedsNewApproval):
            r.vision("review", [], project_dir=p,
                     grant=self.grant(p, "review", 0.003, model="primary"), allow_paid=True)
        self.assertEqual(Script.log, [("g", "primary", "vision")])

    def test_unknown_vision_requires_approved_provider_and_model_not_chain_position(self):
        for provider, model in (("o", "primary"), ("g", "other")):
            with self.subTest(provider=provider, model=model):
                r, p = setup(chains={"vision": ch((provider, model))})
                with self.assertRaises(R.NeedsNewApproval):
                    r.vision("review", [], project_dir=p,
                             grant=self.grant(p, "review", 0.003, model="primary"), allow_paid=True)
                self.assertEqual(Script.log, [])

    def test_unknown_vision_without_approved_provider_fails_closed(self):
        r, p = setup(chains={"vision": ch(("g", "primary"))})
        with self.assertRaises(R.NeedsNewApproval):
            r.vision("review", [], project_dir=p,
                     grant=self.grant(p, "review", 0.003, model="primary", provider=None), allow_paid=True)
        self.assertEqual(Script.log, [])

    def test_unknown_vision_fallback_is_skipped_for_free_model(self):
        r, p = setup({"g": {"primary": [Rejected("blocked")]}},
                     {"vision": ch(("g", "primary"), ("g", "unknown"), ("o", "gpt"))})
        r.pricing.overrides[key("g", "primary")] = {"kind": "text", "per_call": 0.003}
        out = r.vision("review", [], project_dir=p,
                       grant=self.grant(p, "review", 0.003, model="primary"), allow_paid=True)
        self.assertEqual((out["model"], out["cost"]), ("gpt", 0.0))
        self.assertEqual(Script.log, [("g", "primary", "vision"), ("o", "gpt", "vision")])

    def test_image_price_rule(self):
        r, p = setup(chains={"image": ch(("g", "img"))})
        grant = self.grant(p, "image", 0.04)
        out = r.image("p", project_dir=p, grant=grant)
        self.assertEqual((out["cost"], out["cost_source"]), (0.04, "computed"))

    def test_unknown_price_blocks_when_approved_price_given(self):
        r, p = setup(chains={"image": ch(("g", "mystery"))})
        with self.assertRaises(R.NeedsNewApproval) as c:
            r.image("p", project_dir=p, grant=self.grant(p, "image", 1.0))
        self.assertIn("price unknown", str(c.exception))
        self.assertIsNone(c.exception.price)
        self.assertEqual(Script.log, [])

    def test_unknown_image_and_video_fallback_need_new_approval(self):
        for role, kind, primary, price, operation in (("image", "image", "img", 0.04, "image"),
                                                    ("video", "clip", "veo", 0.2, "submit")):
            with self.subTest(role=role):
                r, p = setup({"g": {primary: [Rejected("blocked")]}},
                             {role: ch(("g", primary), ("g", "unknown"))})
                with self.assertRaises(R.NeedsNewApproval) as c:
                    getattr(r, role)(self.REQ if role == "video" else "p", project_dir=p,
                                     grant=self.grant(p, kind, price, model=primary))
                self.assertEqual(c.exception.entry["model"], "unknown")
                self.assertIsNone(c.exception.price)
                self.assertEqual(Script.log, [("g", primary, operation)])

    def test_video_fallback_only_if_not_dearer(self):
        # primary submit fails; chain: veo ($0.05/s), veo2 ($0.5/s, too dear), kling ($0.02/s)
        r, p = setup({"g": {"veo": [Rejected("HTTP 400")]}}, {"video": ch(("g", "veo"), ("r", "veo2"), ("k", "kling-v1"))})
        out = r.video(self.REQ, project_dir=p, grant=self.grant(p, "clip", 0.2))
        self.assertEqual((out["status"], out["provider"], out["cost"]), ("done", "k", 0.08))
        self.assertNotIn(("r", "veo2", "submit"), Script.log)

    def test_needs_new_approval_when_only_dearer_left(self):
        r, p = setup({"g": {"veo": [Rejected("HTTP 400")]}}, {"video": ch(("g", "veo"), ("r", "veo2"))})
        with self.assertRaises(R.NeedsNewApproval) as c:
            r.video(self.REQ, project_dir=p, grant=self.grant(p, "clip", 0.2))
        self.assertEqual(c.exception.entry["model"], "veo2")
        self.assertEqual(c.exception.price, 2.0)

    def test_accepted_job_that_fails_is_not_resubmitted(self):
        r, p = setup({"g": {"poll:veo": [{"status": "failed", "error": "policy", "cost": 0.1}]}}, {"video": ch(("g", "veo"), ("k", "kling-v1"))})
        out = r.video(self.REQ, project_dir=p, grant=self.grant(p, "clip", 0.2))
        self.assertEqual((out["status"], out["error"], out["provider"]), ("failed", "policy", "g"))
        self.assertEqual([a for a in Script.log if a[2] == "submit"], [("g", "veo", "submit")])

    def test_timeout_returns_pending_job(self):
        t = [0.0]
        r, p = setup({"g": {"poll:veo": [{"status": "pending", "error": None, "cost": None}]}}, {"video": ch(("g", "veo"))})
        r.clock = lambda: (t.__setitem__(0, t[0] + 100) or t[0])
        r.sleep = lambda s: None
        out = r.video(self.REQ, project_dir=p, grant=self.grant(p, "clip", 0.2), timeout=250)
        self.assertEqual(out["status"], "pending")
        self.assertEqual(out["job"], {"job_id": "J-veo", "model": "veo", "provider": "g"})

    def test_fetch_video_after_timeout(self):
        r, _ = setup(chains={"video": ch(("g", "veo"))})
        out = r.fetch_video({"job_id": "J-veo", "model": "veo", "provider": "g"}, self.REQ)
        self.assertEqual((out["status"], out["bytes"], out["cost"], out["cost_source"]), ("done", b"MP4", 0.2, "computed"))


if __name__ == "__main__":
    unittest.main()
