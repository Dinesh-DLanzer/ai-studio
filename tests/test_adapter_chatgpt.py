import base64
import json
import tempfile
import time
import unittest
from pathlib import Path

from aistudio.providers import chatgpt_auth as ca
from aistudio.providers.adapters.chatgpt import ChatGPTAdapter
from aistudio.providers.base import AuthError, ProviderError, Rejected, Retryable
from tests._adapter_helpers import B64_PIXEL, FakeTransport, png


def jwt(**claims):
    enc = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()
    return f"{enc({'alg': 'none'})}.{enc(claims)}.sig"


def sse(*events):
    return ("".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n" for e in events)).encode()


FRESH = jwt(exp=int(time.time()) + 3600, **{"https://api.openai.com/auth": {"chatgpt_account_id": "acct-1", "chatgpt_plan_type": "plus"}})
SECRET = {"access_token": FRESH, "refresh_token": "rt-1", "account_id": "acct-1", "expires_at": str(int(time.time()) + 3600)}
CONN = {"id": "chatgpt", "type": "chatgpt", "secret": SECRET}
URL = "https://chatgpt.com/backend-api/codex/responses"
DONE = {"type": "response.completed", "response": {"usage": {"input_tokens": 7, "output_tokens": 3}}}


def make(*answers, conn=CONN):
    t = FakeTransport(*answers)
    return ChatGPTAdapter(dict(conn, secret=dict(conn["secret"])), transport=t), t


class TestChatGPTAuth(unittest.TestCase):
    def test_codex_token_import(self):
        d = Path(tempfile.mkdtemp())
        (d / "auth.json").write_text(json.dumps({"OPENAI_API_KEY": None, "tokens": {"access_token": FRESH, "refresh_token": "rt-9", "id_token": "", "account_id": "acct-7"}}))
        secret, preview = ca.read_codex_session(d / "auth.json")
        self.assertEqual((secret["refresh_token"], secret["account_id"]), ("rt-9", "acct-7"))
        self.assertTrue(preview["signed_in"] and not preview["expired"])
        self.assertEqual(preview["plan"], "plus")
        self.assertNotIn(FRESH, json.dumps(preview))

    def test_codex_import_errors(self):
        d = Path(tempfile.mkdtemp())
        with self.assertRaises(ProviderError):
            ca.read_codex_session(d / "missing.json")
        (d / "auth.json").write_text(json.dumps({"OPENAI_API_KEY": "sk-x"}))
        with self.assertRaises(ProviderError):
            ca.read_codex_session(d / "auth.json")

    def test_pkce_and_authorize_url(self):
        pk = ca.new_pkce()
        want = base64.urlsafe_b64encode(__import__("hashlib").sha256(pk["verifier"].encode()).digest()).rstrip(b"=").decode()
        self.assertEqual(pk["challenge"], want)
        url = ca.authorize_url(pk)
        self.assertIn("code_challenge_method=S256", url)
        self.assertIn("client_id=" + ca.CLIENT_ID, url)
        self.assertIn("state=" + pk["state"], url)

    def test_exchange_code_is_form_encoded(self):
        t = FakeTransport({"access_token": FRESH, "refresh_token": "rt-new"})
        s = ca.exchange_code(t, "the-code", "ver")
        self.assertIn("form", t.last["headers"]["Content-Type"])
        self.assertEqual(t.last["body"]["code_verifier"], "ver")
        self.assertEqual((s["refresh_token"], s["account_id"]), ("rt-new", "acct-1"))

    def test_token_refresh(self):
        saved = []
        new_access = jwt(exp=int(time.time()) + 7200)
        old = {**SECRET, "expires_at": str(int(time.time()) - 10)}
        t = FakeTransport({"access_token": new_access, "refresh_token": "rt-2"}, sse({"type": "response.output_text.delta", "delta": "hi"}, DONE))
        a = ChatGPTAdapter({"id": "c", "type": "chatgpt", "secret": old, "on_secret": saved.append}, transport=t)
        self.assertEqual(a.chat("gpt-5", [{"role": "user", "content": "x"}])["text"], "hi")
        r = t.calls[0]
        self.assertEqual((r["url"], r["body"]["grant_type"], r["body"]["refresh_token"], r["body"]["client_id"]), (ca.TOKEN_URL, "refresh_token", "rt-1", ca.CLIENT_ID))
        self.assertEqual(saved[0]["refresh_token"], "rt-2")
        self.assertEqual(t.last["headers"]["Authorization"], "Bearer " + new_access)

    def test_refresh_revoked_is_auth_error(self):
        old = {**SECRET, "expires_at": "1"}
        with self.assertRaises(AuthError):
            ca.valid_secret(FakeTransport(Rejected("HTTP 400: invalid_grant")), old)


class TestChatGPTAdapter(unittest.TestCase):
    def test_chat_completion(self):
        a, t = make(sse({"type": "response.output_text.delta", "delta": "Hel"}, {"type": "response.output_text.delta", "delta": "lo"}, DONE))
        res = a.chat("gpt-5", [{"role": "system", "content": "Be brief"}, {"role": "user", "content": "Hi"}, {"role": "assistant", "content": "Yo"}, {"role": "user", "content": "Again"}])
        self.assertEqual((res["text"], res["usage"], res["cost"]), ("Hello", {"input": 7, "output": 3}, 0.0))
        c = t.last
        self.assertEqual((c["method"], c["url"], c["raw"]), ("POST", URL, True))
        self.assertEqual(c["headers"]["chatgpt-account-id"], "acct-1")
        self.assertEqual(c["body"]["instructions"], "Be brief")
        self.assertTrue(c["body"]["stream"] and c["body"]["store"] is False)
        self.assertEqual([m["role"] for m in c["body"]["input"]], ["user", "assistant", "user"])
        self.assertEqual(c["body"]["input"][1]["content"][0]["type"], "output_text")

    def test_empty_answer_and_failure(self):
        a, _ = make(sse(DONE))
        with self.assertRaises(Retryable):
            a.chat("gpt-5", [{"role": "user", "content": "x"}])
        a, _ = make(sse({"type": "response.failed", "response": {"error": {"message": "boom"}}}))
        with self.assertRaises(Retryable):
            a.chat("gpt-5", [{"role": "user", "content": "x"}])

    def test_vision_payload(self):
        a, t = make(sse({"type": "response.output_text.delta", "delta": "two"}, DONE))
        a.vision("gpt-5", "what?", [png("a.png"), png("b.png")])
        parts = t.last["body"]["input"][0]["content"]
        self.assertEqual([p["type"] for p in parts], ["input_text", "input_image", "input_image"])
        self.assertTrue(parts[1]["image_url"].startswith("data:image/png;base64,"))

    def test_image_extraction(self):
        a, t = make(sse({"type": "response.output_item.done", "item": {"type": "image_generation_call", "result": B64_PIXEL}}, DONE))
        res = a.image("gpt-image-1", "a cat", aspect_ratio="16:9")
        self.assertEqual(res["bytes"], b"IMGBYTES")
        self.assertEqual(t.last["body"]["tools"][0]["size"], "1536x1024")
        a, _ = make(sse(DONE))
        with self.assertRaises(Retryable):
            a.image("gpt-image-1", "a cat")

    def test_models_and_test(self):
        a, _ = make(sse({"type": "response.output_text.delta", "delta": "OK"}, DONE))
        self.assertIn("gpt-image-1", [m["id"] for m in a.list_models() if m["capability"] == "image"])
        self.assertTrue(a.test()["ok"])
        a, _ = make(AuthError("HTTP 401"))
        self.assertFalse(a.test()["ok"])

    def test_models_come_from_codex_install(self):
        from aistudio.providers.adapters.chatgpt import chat_models
        d = Path(tempfile.mkdtemp())
        (d / "models_cache.json").write_text(json.dumps({"models": [
            {"slug": "hidden", "visibility": "hide", "priority": 1}, {"slug": "b", "visibility": "list", "priority": 9}, {"slug": "a", "visibility": "list", "priority": 2}]}))
        (d / "config.toml").write_text('model = "mine"\nmodel_reasoning_effort = "high"\n')
        self.assertEqual(chat_models(d), ["mine", "a", "b"])
        self.assertEqual(chat_models(Path(tempfile.mkdtemp()))[0], "gpt-5.6-luna")

    def test_video_unsupported(self):
        from aistudio.providers.base import Unsupported
        a, _ = make()
        with self.assertRaises(Unsupported):
            a.video_submit("m", {})


if __name__ == "__main__":
    unittest.main()


class TestChatGPTPricing(unittest.TestCase):
    def test_subscription_models_are_free_unless_the_user_sets_a_price(self):
        from aistudio.pricing import Pricing
        pr = Pricing()
        self.assertTrue(pr.is_free(pr.card("chatgpt", "chatgpt", "gpt-6-luna")))
        self.assertEqual(pr.image_price(pr.card("chatgpt", "chatgpt", "gpt-image-1")), 0.0)
        self.assertTrue(pr.is_free(pr.card("chatgpt", "chatgpt", "gpt-image-1")))
        custom = {"kind": "image", "per_image": 0.05}
        pr = Pricing(overrides={"chatgpt|gpt-image-1": custom})
        self.assertEqual(pr.image_price(pr.card("chatgpt", "chatgpt", "gpt-image-1")), 0.05)


class TestFreeCards(unittest.TestCase):
    def test_zero_priced_image_and_video_count_as_free(self):
        from aistudio.pricing import Pricing
        pr = Pricing()
        self.assertTrue(pr.is_free({"kind": "video", "per_second": {"720p": 0, "1080p": 0}}))
        self.assertFalse(pr.is_free({"kind": "video", "per_second": {"720p": 0.05}}))
        self.assertFalse(pr.is_free({"kind": "video", "per_second": {"720p": {"audio": 0.1, "no_audio": 0}}}))
        self.assertFalse(pr.is_free({"kind": "image", "per_image": 0.04}))
