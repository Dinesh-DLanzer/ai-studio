import unittest

from aistudio.delivery import ffmpeg_args, get_preset, load_presets, preflight


class DeliveryTests(unittest.TestCase):
    def test_all_presets_validate(self):
        presets = load_presets()
        self.assertEqual(
            set(presets),
            {"youtube", "youtube-shorts", "instagram-reel", "tiktok", "linkedin", "x"},
        )
        for preset_id in presets:
            self.assertEqual(get_preset(preset_id)["id"], preset_id)

    def test_ffmpeg_args_for_tiktok(self):
        self.assertEqual(
            ffmpeg_args(get_preset("tiktok"), "input.mov", "output.mp4"),
            [
                "-i", "input.mov", "-c:v", "libx264", "-crf", "23",
                "-maxrate", "6000k", "-bufsize", "12000k", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", "128k", "-ar", "48000",
                "-movflags", "+faststart", "output.mp4",
            ],
        )

    def test_preflight_reports_aspect_duration_and_audio(self):
        preset = get_preset("youtube-shorts")
        issues = preflight(
            preset,
            {"duration": 70, "width": 1920, "height": 1080, "audio": False},
        )
        codes = {issue["code"] for issue in issues if issue["level"] == "error"}
        self.assertTrue({"aspect_ratio", "duration_max", "audio_missing"}.issubset(codes))

    def test_invalid_preset_id_raises_value_error(self):
        with self.assertRaisesRegex(ValueError, "unknown delivery preset"):
            get_preset("not-a-platform")

    def test_preflight_warns_for_text_in_unsafe_band(self):
        issues = preflight(
            get_preset("tiktok"),
            {"duration": 12, "width": 1080, "height": 1920, "audio": True},
            {"tracks": {"text": [{"id": "caption", "y": 0.95}]}},
        )
        self.assertTrue(any(issue["code"] == "text_safe_area" and issue["level"] == "warn" for issue in issues))


if __name__ == "__main__":
    unittest.main()
