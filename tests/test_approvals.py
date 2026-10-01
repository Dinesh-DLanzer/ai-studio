import tempfile, unittest
from pathlib import Path
from aistudio import approvals as A


class TestApprovals(unittest.TestCase):
    def setUp(self):
        self.p = Path(tempfile.mkdtemp())
        self.req = dict(kind="clip", shot="s01", model="google/veo-3.1-lite", price=0.2, payload={"prompt": "x", "frame": "a.png"})

    def prop(self, **kw):
        return A.propose(self.p, reveal_code=kw.pop("reveal_code", True), **dict(self.req, **kw))

    def test_agent_proposal_has_no_code(self):
        r = A.propose(self.p, **self.req)
        self.assertNotIn("code", r)
        self.assertNotIn("code_sha", r)
        self.assertNotIn("code", A.get(self.p, r["id"]))
        self.assertNotIn("code_sha", A.get(self.p, r["id"]))

    def test_happy_path_once(self):
        r = self.prop()
        self.assertEqual(r["status"], "pending")
        self.assertEqual(A.approve(self.p, r["id"], r["code"])["status"], "approved")
        self.assertTrue(A.consume(self.p, r["id"], **self.req))
        with self.assertRaises(A.ApprovalError):
            A.consume(self.p, r["id"], **self.req)  # single use

    def test_not_approved_cannot_consume(self):
        r = self.prop()
        with self.assertRaises(A.ApprovalError):
            A.consume(self.p, r["id"], **self.req)

    def test_wrong_code_and_lock(self):
        r = self.prop()
        for _ in range(A.MAX_TRIES):
            with self.assertRaises(A.ApprovalError):
                A.approve(self.p, r["id"], "000000" if r["code"] != "000000" else "111111")
        with self.assertRaises(A.ApprovalError):
            A.approve(self.p, r["id"], r["code"])  # locked even with the right code

    def test_changed_request_voids(self):
        for change in ({"price": 0.4}, {"model": "other"}, {"shot": "s02"}, {"payload": {"prompt": "y", "frame": "a.png"}}):
            r = self.prop()
            A.approve(self.p, r["id"], r["code"])
            with self.assertRaises(A.ApprovalError):
                A.consume(self.p, r["id"], **dict(self.req, **change))
            self.assertEqual(A.get(self.p, r["id"])["status"], "void")

    def test_expiry(self):
        r = A.propose(self.p, reveal_code=True, ttl=10, now=1000.0, **self.req)
        with self.assertRaises(A.ApprovalError):
            A.approve(self.p, r["id"], r["code"], now=1011.0)
        r2 = A.propose(self.p, reveal_code=True, ttl=10, now=1000.0, **self.req)
        A.approve(self.p, r2["id"], r2["code"], now=1005.0)
        with self.assertRaises(A.ApprovalError):
            A.consume(self.p, r2["id"], now=1020.0, **self.req)

    def test_reject_and_unknown(self):
        r = self.prop()
        A.reject(self.p, r["id"])
        with self.assertRaises(A.ApprovalError):
            A.approve(self.p, r["id"], r["code"])
        with self.assertRaises(A.ApprovalError):
            A.get(self.p, "nope")

    def test_payload_order_and_unicode(self):
        a = A.request_hash("clip", "s1", "m", 0.2, {"a": 1, "b": "கடை"})
        b = A.request_hash("clip", "s1", "m", 0.20, {"b": "கடை", "a": 1})
        self.assertEqual(a, b)

    def test_human_channel_approval(self):
        r = A.propose(self.p, summary={"prompt": "x"}, **self.req)      # agent-style: no code
        self.assertEqual(A.get(self.p, r["id"])["summary"], {"prompt": "x"})
        self.assertEqual(A.approve_human(self.p, r["id"])["status"], "approved")
        self.assertTrue(A.consume(self.p, r["id"], **self.req))
        with self.assertRaises(A.ApprovalError):
            A.approve_human(self.p, r["id"])                            # already used
        r2 = A.propose(self.p, ttl=5, now=100.0, **self.req)
        with self.assertRaises(A.ApprovalError):
            A.approve_human(self.p, r2["id"], now=200.0)                # expired

    def test_negative_price(self):
        with self.assertRaises(A.ApprovalError):
            self.prop(price=-1)


if __name__ == "__main__":
    unittest.main()
