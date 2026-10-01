import unittest
from aistudio.providers.adapters.fake import FakeAdapter
from aistudio.providers.base import AuthError, NotFound, Rejected, Retryable

A = FakeAdapter()


class TestFakeAdapter(unittest.TestCase):
    def test_text_and_vision(self):
        self.assertEqual(A.chat("fake/llm", [{"role": "user", "content": "hello"}])["text"], "FAKE: hello")
        self.assertIn('"pass"', A.vision("fake/vision", "p", [])["text"])
        self.assertIn('"fail"', A.vision("fake/vision", "p", [], {"inject": "extra_person"})["text"])

    def test_image(self):
        self.assertTrue(A.image("fake/image", "p")["bytes"].startswith(b"\x89PNG"))
        with self.assertRaises(Rejected):
            A.image("fake/image", "p", refs=["a"] * 5)

    def test_video_flow(self):
        job = A.video_submit("fake/video", {"prompt": "p", "seconds": 4, "audio": True})
        self.assertEqual(A.video_poll(job), {"status": "done", "error": None, "cost": 0.2})
        self.assertTrue(A.video_download(job).startswith(b"FAKEMP4"))
        bad = A.video_submit("fake/video", {"prompt": "FAIL_ME", "seconds": 4})
        self.assertEqual(A.video_poll(bad)["status"], "failed")
        with self.assertRaises(Rejected):
            A.video_submit("fake/video", {"prompt": "p", "seconds": 5})

    def test_failure_models(self):
        for model, exc in (("fail-retry", Retryable), ("fail-auth", AuthError), ("fail-reject", Rejected), ("fail-missing", NotFound)):
            with self.assertRaises(exc):
                A.chat(model, [])


if __name__ == "__main__":
    unittest.main()
