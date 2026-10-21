import tests._hermetic as HERM  # noqa: F401  (first: no real keys, no network)
import json
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from aistudio import catalog as catalog_mod, costlog
from aistudio.providers import config as pconf
from aistudio.providers.adapters.replicate import ReplicateAdapter
from aistudio.schemas.catalog import validate_profile
from aistudio.secrets import SecretStore
from aistudio.service import ServiceError, Workspace
from aistudio.domain.spec import _source_resolution
from tests._adapter_helpers import FakeTransport

FIX = Path(__file__).parent / "fixtures" / "replicate" / "model_video.json"
vcard = lambda r: {"kind": "video", "per_second": {"720p": r}}


def make(case, overrides=None):
    HERM.real_projects(case)
    root = Path(tempfile.mkdtemp())
    ws = Workspace(root, secrets=SecretStore(root / "sec"))
    ws.ensure_settings()
    provs = [{"id": "fk", "type": "fake", "label": "FK", "base_url": "", "enabled": True}]
    pconf.save_providers(ws.settings_dir, provs)
    doc = pconf.default_roles()
    doc["roles"]["video"]["chain"] = [{"provider": "fk", "model": "vid-a"}, {"provider": "fk", "model": "vid-b"}]
    doc["roles"]["image"]["chain"] = [{"provider": "fk", "model": "img-a"}]
    pconf.save_roles(ws.settings_dir, doc, provs)
    caps = {"fk|vid-b": {"frames": {"end": True}}, **(overrides or {})}
    (ws.settings_dir / "models.json").write_text(json.dumps({"prices": {
        "fk|vid-a": vcard(0.10), "fk|vid-b": vcard(0.30), "fk|img-a": {"kind": "image", "per_image": 0.04}}, "capabilities": caps}))
    ws.create_project("demo")
    return ws, ws.pdir("demo")


def shots(ws, *items):
    ws.put_shots("demo", {"aspect_ratio": "9:16", "final_resolution": "720p", "shots": [{"id": i[0], "prompt": "p", "model": "google/veo-3.1-lite", "seconds": i[1], "resolution": "720p", **i[2]} for i in items]})


class TestLookupOrder(unittest.TestCase):
    def test_source_resolution_price_bucket_uses_probe_height(self):
        p = Path(tempfile.mkdtemp())
        with patch("aistudio.editor.probe", return_value={"height": 1080}):
            self.assertEqual(_source_resolution(p, {"source": "clips/source.mp4"}), "1080p")
        with patch("aistudio.editor.probe", return_value={"height": 2160}):
            self.assertEqual(_source_resolution(p, {"source": "clips/source.mp4"}), "4k")
        with patch("aistudio.editor.probe", return_value=None):
            self.assertEqual(_source_resolution(p, {"source": "clips/fake.mp4"}), "720p")

    def test_user_over_cache_over_builtin_over_default(self):
        d = Path(tempfile.mkdtemp())
        cat = catalog_mod.Catalog(d)
        end = lambda: cat.profile("g", "google", "veo-3.1-generate-preview")
        self.assertTrue(end()["frames"]["end"])
        self.assertEqual(end()["source"], "builtin")
        self.assertFalse(cat.profile("g", "google", "unknown-model")["frames"]["end"])      # conservative default
        self.assertEqual(cat.profile("g", "google", "unknown-model")["camera"]["mode"], "prompt")
        cat.store("g", "veo-3.1-generate-preview", {"frames": {"end": False}})
        self.assertFalse(end()["frames"]["end"])
        self.assertEqual(end()["source"], "provider_api")
        (d / "models.json").write_text(json.dumps({"capabilities": {"g|veo-3.1-generate-preview": {"frames": {"end": True}}}}))
        self.assertTrue(end()["frames"]["end"])
        self.assertEqual(end()["source"], "user")
        self.assertEqual(validate_profile(end()), [])

    def test_missing_end_frame_and_refs_by_adapter(self):
        cat = catalog_mod.Catalog(Path(tempfile.mkdtemp()))
        need = {"task": "image_to_video", "end_frame": True, "refs": 2}
        veo = cat.profile("g", "google", "veo-3.1-generate-preview")
        self.assertIsNone(catalog_mod.missing(veo, "google", need))
        self.assertIn("reference", catalog_mod.missing(veo, "google", {"refs": 4}))
        self.assertIn("reference", catalog_mod.missing(cat.profile("g", "google", "veo-3.1-lite-generate-preview"), "google", {"refs": 1}))
        self.assertIn("keyframe", catalog_mod.missing({**veo, "frames": {**veo["frames"], "keyframes": 2}}, "google", {"keyframes": 2}))
        for ptype, model in (("kling", "kling-v2"), ("runway", "gen4_turbo"), ("openrouter", "google/veo-3.1")):
            self.assertTrue(catalog_mod.missing(cat.profile("x", ptype, model), ptype, need), ptype)
        # an adapter that cannot send refs is refused even when the profile allows them
        permissive = {**veo, "frames": {**veo["frames"], "end": True}, "references": {"max": 3, "roles": []}}
        self.assertIn("reference", catalog_mod.missing(permissive, "kling", {"task": "image_to_video", "refs": 1}))

    def test_validate_profile_rejects_bad_values(self):
        self.assertTrue(validate_profile({"camera": {"mode": "native"}}))       # native needs a param
        self.assertTrue(validate_profile({"audio": "loud"}))

    def test_every_builtin_entry_is_valid_and_rates_models_are_covered(self):
        cat = catalog_mod.Catalog(Path(tempfile.mkdtemp()))
        for e in cat.entries:
            self.assertEqual(validate_profile({**e["profile"], "source": "builtin"}), [], e["pattern"])
        for m in json.loads(Path("rates.json").read_text())["models"]:
            self.assertIsNotNone(cat.builtin("openrouter", m), m)
        self.assertIsNotNone(cat.builtin("openrouter", "qwen/qwen-image-3"))
        for t, m in (("kling", "kling-v2-master"), ("runway", "gen4_turbo"), ("google", "veo-3.1-generate-preview"), ("google", "imagen-4.0-generate")):
            self.assertIsNotNone(cat.builtin(t, m), m)


class TestReplicateDescribe(unittest.TestCase):
    def test_schema_maps_to_profile(self):
        t = FakeTransport(json.loads(FIX.read_text()))
        a = ReplicateAdapter({"id": "rp", "type": "replicate", "secret": {"api_key": "r8_x"}}, transport=t, sleep=lambda s: None)
        part = a.describe_model("acme/clipper")
        self.assertTrue(part["frames"]["end"])
        self.assertEqual(part["durations"], [5, 10])
        self.assertEqual(part["aspect_ratios"], ["16:9", "9:16"])
        self.assertEqual(part["references"]["max"], 3)
        self.assertEqual((part["camera"]["mode"], part["camera"]["param"], part["camera"]["native"]), ("native", "camera_motion", ["pan_left", "zoom_in"]))
        self.assertTrue(part["seed"])
        self.assertFalse(part["negative_prompt"])
        d = Path(tempfile.mkdtemp())
        cat = catalog_mod.Catalog(d)
        a.transport = FakeTransport(json.loads(FIX.read_text()))
        cat.refresh("rp", a, "acme/clipper")
        self.assertEqual(cat.profile("rp", "replicate", "acme/clipper")["source"], "provider_api")
        self.assertIsNone(ReplicateAdapter({"id": "rp", "type": "replicate", "secret": {}}, transport=FakeTransport({"x": 1})).describe_model("a/b"))


class TestResolver(unittest.TestCase):
    def test_per_shot_model_is_used_by_estimate_proposal_and_execute(self):
        ws, p = make(self)
        shots(ws, ("s1", 4, {"model": "fk|vid-b"}), ("s2", 4, {}))
        est = ws.estimate("demo", failure=0)
        self.assertEqual([round(x["cost"], 3) for x in est["per_shot"]], [1.2, 0.4])        # 4s x 0.30 and 4s x 0.10
        self.assertEqual(ws.spec("demo", "clip", "s1")["model"], "vid-b")
        self.assertEqual(ws.spec("demo", "clip", "s2")["model"], "vid-a")
        ws.approve_budget("demo")
        prop = ws.propose("demo", "clip", "s1")
        self.assertEqual((prop["model"], prop["price"]), ("vid-b", 1.2))
        self.assertIn("profile", prop["summary"])
        ws.approve_human("demo", prop["id"])
        res = ws.execute("demo", prop["id"])
        self.assertEqual(res["kind"], "clip")      # the fake adapter reports its own cost, so the row is checked for model, not cost
        row = costlog.read_log(p)[-1]
        self.assertEqual((row["model"], row["provider"]), ("vid-b", "fk"))
        self.assertEqual(ws.pipeline_domain._item_price(p, "clip", "s2"), (0.4, "vid-a"))      # the batch plan prices the same spec

    def test_changing_a_shot_model_price_makes_the_budget_stale(self):
        ws, p = make(self)
        shots(ws, ("s1", 4, {"model": "fk|vid-b"}))
        ws.estimate("demo")
        ws.approve_budget("demo")
        b = json.loads((p / "budget.json").read_text())
        self.assertIsNone(ws._costs.stale_budget(p, b))
        doc = json.loads((ws.settings_dir / "models.json").read_text())
        doc["prices"]["fk|vid-b"] = vcard(0.50)
        (ws.settings_dir / "models.json").write_text(json.dumps(doc))
        self.assertIsNotNone(ws._costs.stale_budget(p, b))

    def test_runner_skips_chain_entries_without_end_frame_support(self):
        ws, p = make(self)
        used = []
        r = ws.runner().run("video", lambda a, m: used.append(m) or "ok", p, required={"task": "image_to_video", "end_frame": True, "refs": 0})
        self.assertEqual((used, r["model"]), (["vid-b"], "vid-b"))
        self.assertEqual(r["attempts"][0]["error"], "skipped: no end-frame support")

    def test_chain_pick_satisfies_end_frame_and_explicit_model_errors(self):
        ws, p = make(self)
        (p / "stills").mkdir(exist_ok=True)
        (p / "stills" / "e.png").write_bytes(b"x")
        shots(ws, ("s1", 4, {"end_frame": "stills/e.png"}), ("s2", 4, {"end_frame": "stills/e.png", "model": "fk|vid-a"}))
        self.assertEqual(ws.spec("demo", "clip", "s1")["model"], "vid-b")        # vid-a lacks end frames, so the next chain entry is chosen
        with self.assertRaises(ServiceError) as c:
            ws.spec("demo", "clip", "s2")
        self.assertIn("no end-frame support", str(c.exception))
        self.assertIn("vid-a", str(c.exception))
        self.assertIn("google:veo-3.1*", str(c.exception))

    def test_duration_snaps_with_a_warning_and_prices_the_snapped_seconds(self):
        ws, p = make(self, {"fk|vid-a": {"durations": [4, 8]}})
        shots(ws, ("s1", 6, {}))
        sp = ws.spec("demo", "clip", "s1")
        self.assertEqual(sp["seconds"], 4)
        self.assertTrue(any("6s is not offered" in w for w in sp["warnings"]))
        self.assertAlmostEqual(sp["price"], 0.4)
        self.assertAlmostEqual(ws.estimate("demo", failure=0)["per_shot"][0]["cost"], 0.4)

    def test_too_many_references_is_an_error_naming_the_limit(self):
        ws, p = make(self, {"fk|img-a": {"references": {"max": 1}}})
        ws.put_images("demo", {"style": "", "images": [
            {"id": "a", "kind": "character", "out": "stills/a.png", "prompt": "x", "refs": []},
            {"id": "b", "kind": "character", "out": "stills/b.png", "prompt": "x", "refs": []},
            {"id": "c", "kind": "background", "out": "stills/c.png", "prompt": "x", "refs": ["a", "b"]}]})
        with self.assertRaises(ServiceError) as c:
            ws.spec("demo", "image", "c")
        self.assertIn("at most 1 reference", str(c.exception))
        self.assertEqual(ws.spec("demo", "image", "a")["model"], "img-a")

    def test_spec_preview_endpoint_is_read_only_and_agent_allowed(self):
        try:
            from fastapi.testclient import TestClient
            from server import api_docs
            from server.app import create_app
        except Exception:
            self.skipTest("needs fastapi")
        ws, p = make(self)
        shots(ws, ("s1", 4, {"model": "fk|vid-b"}))
        c = TestClient(create_app(str(ws.root), token="tok", static_dir="/nonexistent"))
        r = c.get("/api/projects/demo/spec/clip/s1", headers={"x-aistudio-token": "tok"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual((r.json()["model"], r.json()["profile"]["frames"]["end"]), ("vid-b", True))
        self.assertTrue(api_docs.agent_allowed("GET", "/api/projects/{name}/spec/{kind}/{target}"))
        self.assertEqual(c.get("/api/projects/demo/spec/nope/s1", headers={"x-aistudio-token": "tok"}).status_code, 400)


if __name__ == "__main__":
    unittest.main()
