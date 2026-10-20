import json
import tempfile
import unittest
from pathlib import Path

from aistudio.providers import config as C
from aistudio.providers.adapters.comfyui import ComfyUIAdapter
from aistudio.providers.adapters.comfyui_manifest import apply_inputs, load_manifest
from aistudio.providers.base import NotFound, Rejected, Retryable
from tests._adapter_helpers import FakeTransport, png

CONN = {"id": "cu", "type": "comfyui", "secret": {}}
BASE = "http://127.0.0.1:8188"
FIXTURES = Path(__file__).parent / "fixtures" / "comfyui"
REQ = {"prompt": "a cat", "seconds": 5, "resolution": "480p", "aspect_ratio": "9:16", "audio": False, "first_frame": None}
DONE = {"outputs": {"9": {"images": [{"filename": "out.png", "subfolder": "sub", "type": "output"}]}},
        "status": {"status_str": "success", "completed": True}}
VIDEO_DONE = {"outputs": {"30": {"gifs": [{"filename": "clip.mp4", "subfolder": "", "type": "output"}]}},
              "status": {"status_str": "success", "completed": True}}


def make(*answers, **kw):
    t = FakeTransport(*answers)
    return ComfyUIAdapter(CONN, transport=t, sleep=lambda s: None, **kw), t


def broken_workflow(manifest):
    """A workflow folder (called "broken") whose manifest points at something the workflow does not have."""
    root = Path(tempfile.mkdtemp())
    d = root / "broken"
    d.mkdir()
    (d / "workflow_api.json").write_text(json.dumps({"6": {"class_type": "CLIPTextEncode", "inputs": {"text": "x"}}}))
    (d / "manifest.json").write_text(json.dumps(manifest))
    return root, d


class TestComfyUIAdapter(unittest.TestCase):
    def test_health_check(self):
        a, t = make({"system": {"comfyui_version": "0.3.40"}})
        r = a.test()
        self.assertTrue(r["ok"])
        self.assertIn("0.3.40", r["message"])
        self.assertEqual(t.last["url"], BASE + "/system_stats")

    def test_health_check_never_raises(self):
        a, _ = make(Retryable("network error: connection refused"))
        r = a.test()
        self.assertFalse(r["ok"])
        self.assertIn("connection refused", r["message"])

    def test_image_runs_the_workflow_and_fetches_the_file(self):
        a, t = make({"prompt_id": "P1", "number": 1, "node_errors": {}}, {"P1": DONE}, b"PNGBYTES",
                     workflows_dir=str(FIXTURES))
        r = a.image("tiny", "a cat")
        self.assertEqual(r["bytes"], b"PNGBYTES")
        self.assertIsNone(r["cost"])
        self.assertEqual(r["model"], "tiny")
        self.assertEqual(t.calls[0]["method"], "POST")
        self.assertEqual(t.calls[0]["url"], BASE + "/prompt")
        self.assertIn("client_id", t.calls[0]["body"])
        sent = t.calls[0]["body"]["prompt"]
        self.assertEqual(sent["6"]["inputs"]["text"], "a cat")
        self.assertIsInstance(sent["3"]["inputs"]["seed"], int)
        self.assertEqual(t.calls[1]["url"], BASE + "/history/P1")
        self.assertEqual(t.calls[2]["url"], BASE + "/view?filename=out.png&subfolder=sub&type=output")
        self.assertTrue(t.calls[2]["raw"])

    def test_image_ignores_a_reference_the_manifest_does_not_map(self):
        a, t = make({"prompt_id": "P1"}, {"P1": DONE}, b"PNGBYTES", workflows_dir=str(FIXTURES))
        a.image("tiny", "a cat", refs=[png("cat.png")])
        self.assertEqual(t.calls[0]["body"]["prompt"]["6"]["inputs"]["text"], "a cat")

    def test_video_submit_poll_and_download(self):
        a, t = make({"prompt_id": "P2"}, {}, {"P2": VIDEO_DONE}, {"P2": VIDEO_DONE}, b"MP4",
                     workflows_dir=str(FIXTURES))
        job = a.video_submit("tiny-video", REQ)
        self.assertEqual(job, {"job_id": "P2", "model": "tiny-video"})
        sent = t.calls[0]["body"]["prompt"]
        self.assertEqual(sent["10"]["inputs"]["text"], "a cat")
        self.assertEqual(sent["20"]["inputs"]["length"], 80)      # 5 seconds at 16 fps
        self.assertEqual(a.video_poll(job)["status"], "pending")
        self.assertEqual(a.video_poll(job), {"status": "done", "error": None, "cost": None})
        self.assertEqual(a.video_download(job), b"MP4")
        self.assertEqual(t.calls[-1]["url"], BASE + "/view?filename=clip.mp4&subfolder=&type=output")

    def test_video_submit_maps_the_first_frame(self):
        a, t = make({"prompt_id": "P2"}, workflows_dir=str(FIXTURES))
        a.video_submit("tiny-video", {**REQ, "first_frame": png("start.png")})
        self.assertEqual(t.calls[0]["body"]["prompt"]["11"]["inputs"]["image"], "start.png")

    def test_failed_run_is_rejected(self):
        a, _ = make({"prompt_id": "P3"},
                    {"P3": {"outputs": {}, "status": {"status_str": "error", "completed": False,
                                                     "messages": [["execution_error", {"exception_message": "CUDA out of memory"}]]}}},
                    workflows_dir=str(FIXTURES))
        with self.assertRaises(Rejected) as cm:
            a.image("tiny", "a cat")
        self.assertIn("CUDA out of memory", str(cm.exception))

    def test_failed_video_run(self):
        failed = {"P4": {"outputs": {}, "status": {"status_str": "error", "completed": False,
                                                  "messages": [["execution_error", {"exception_message": "node 3 failed"}]]}}}
        a, _ = make(failed, failed)
        st = a.video_poll({"job_id": "P4", "model": "tiny-video"})
        self.assertEqual(st["status"], "failed")
        self.assertIn("node 3 failed", st["error"])
        with self.assertRaises(Rejected):
            a.video_download({"job_id": "P4", "model": "tiny-video"})

    def test_refused_workflow_is_rejected(self):
        a, _ = make({"error": {"type": "prompt_outputs_failed_validation", "message": "Prompt outputs failed validation"},
                     "node_errors": {"3": {"errors": [{"type": "value_not_in_list", "message": "ckpt_name not in the list"}]}}},
                     workflows_dir=str(FIXTURES))
        with self.assertRaises(Rejected) as cm:
            a.image("tiny", "a cat")
        self.assertIn("ckpt_name not in the list", str(cm.exception))

    def test_timeout(self):
        a, t = make({"prompt_id": "P4"}, {}, {}, {}, workflows_dir=str(FIXTURES))
        with self.assertRaises(Retryable):
            a.image("tiny", "a cat", opts={"max_polls": 3})
        self.assertEqual(len([c for c in t.calls if c["url"] == BASE + "/history/P4"]), 3)

    def test_cancel_interrupts_and_drops_the_job(self):
        a, t = make({}, {})
        a.cancel("P5")
        self.assertEqual(t.calls[0]["method"], "POST")
        self.assertEqual(t.calls[0]["url"], BASE + "/interrupt")
        self.assertEqual(t.calls[0]["body"], {"prompt_id": "P5"})
        self.assertEqual(t.calls[1]["url"], BASE + "/queue")
        self.assertEqual(t.calls[1]["body"], {"delete": ["P5"]})

    def test_queue_position(self):
        queue = {"queue_running": [[0, "P6", {}]], "queue_pending": [[1, "P7", {}], [2, "P8", {}]]}
        a, t = make(*[lambda *args: queue] * 4)
        self.assertEqual(a.queue_position("P6"), 1)
        self.assertEqual(a.queue_position("P7"), 2)
        self.assertEqual(a.queue_position("P8"), 3)
        self.assertIsNone(a.queue_position("P9"))
        self.assertEqual(t.last["url"], BASE + "/queue")

    def test_list_models_lists_the_installed_workflows(self):
        a, _ = make(workflows_dir=str(FIXTURES))
        models = a.list_models()
        self.assertEqual([m["id"] for m in models], ["tiny", "tiny-video"])
        self.assertEqual([m["capability"] for m in models], ["image", "video"])

    def test_unknown_workflow(self):
        a, _ = make(workflows_dir=str(FIXTURES))
        with self.assertRaises(NotFound):
            a.image("nope", "a cat")

    def test_workflow_without_a_folder_is_not_found(self):
        a, _ = make()
        with self.assertRaises(NotFound):
            a.image("tiny", "a cat")


class TestComfyUIManifest(unittest.TestCase):
    def test_manifest_maps_the_inputs_onto_the_nodes(self):
        m = load_manifest(FIXTURES / "tiny")
        self.assertEqual(m["id"], "tiny")
        self.assertEqual(m["task"], "image")
        self.assertEqual(m["profile"]["resolutions"], ["512x512"])
        wf = apply_inputs(m["workflow"], m, {"prompt": "a dog", "negative_prompt": "ugly", "seed": 7})
        self.assertEqual(wf["6"]["inputs"]["text"], "a dog")
        self.assertEqual(wf["7"]["inputs"]["text"], "ugly")
        self.assertEqual(wf["3"]["inputs"]["seed"], 7)
        self.assertEqual(m["workflow"]["6"]["inputs"]["text"], "a cat")     # the original is untouched

    def test_a_value_the_manifest_does_not_map_is_ignored(self):
        m = load_manifest(FIXTURES / "tiny")
        self.assertEqual(apply_inputs(m["workflow"], m, {"seconds": 5}), m["workflow"])

    def test_seconds_become_frames(self):
        m = load_manifest(FIXTURES / "tiny-video")
        wf = apply_inputs(m["workflow"], m, {"seconds": 5})
        self.assertEqual(wf["20"]["inputs"]["length"], 80)
        self.assertEqual(apply_inputs(m["workflow"], m, {"seconds": 3})["20"]["inputs"]["length"], 48)

    def test_a_node_the_workflow_does_not_have_is_refused(self):
        _, d = broken_workflow({"id": "broken", "task": "image", "inputs": {"prompt": ["9", "text"]}})
        with self.assertRaises(ValueError) as cm:
            load_manifest(d)
        self.assertIn("node '9'", str(cm.exception))

    def test_an_input_the_node_does_not_have_is_refused(self):
        _, d = broken_workflow({"id": "broken", "task": "image", "inputs": {"prompt": ["6", "nope"]}})
        with self.assertRaises(ValueError) as cm:
            load_manifest(d)
        self.assertIn("6.nope", str(cm.exception))

    def test_a_broken_manifest_makes_the_adapter_refuse_the_workflow(self):
        root, _ = broken_workflow({"id": "broken", "task": "image", "inputs": {"prompt": ["9", "text"]}})
        a, _ = make(workflows_dir=str(root))
        with self.assertRaises(Rejected):
            a.image("broken", "a cat")

    def test_a_folder_without_a_manifest_is_refused(self):
        d = Path(tempfile.mkdtemp())
        with self.assertRaises(ValueError):
            load_manifest(d)


class TestComfyUIProviderType(unittest.TestCase):
    def test_the_provider_type_is_registered(self):
        meta = C.PROVIDER_TYPES["comfyui"]
        self.assertEqual(meta["label"], "ComfyUI")
        self.assertEqual(meta["sub"], "Local image and video engine")
        self.assertEqual(meta["fields"], [])
        self.assertTrue(meta["base_url"])
        self.assertEqual(C.capabilities_of("comfyui"), ["image", "video"])


if __name__ == "__main__":
    unittest.main()
