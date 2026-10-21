import tests._hermetic as HERM  # noqa: F401
import unittest

from aistudio import tool_registry
from aistudio.crew import agents

SHIPPED = {"producer", "writer", "director", "scene-designer", "image-artist", "video-director", "editor", "qa"}
NEVER = set(tool_registry.APPROVAL) | set(tool_registry.HUMAN_ONLY) | {"generate_all_plan"}


class ShippedAgentTests(unittest.TestCase):
    def test_every_shipped_agent_loads_and_is_minimal(self):
        loaded = {a["id"]: a for a in agents.list_agents(dirs=[agents.BUILTIN_DIR])}
        self.assertEqual(set(loaded), SHIPPED)
        for a in loaded.values():
            self.assertFalse(set(a["tools"]) & NEVER, a["id"])
            self.assertLessEqual(set(a["tools"]), set(tool_registry.crew_tools()))
            for k, cap in agents.HARD.items():
                self.assertLess(a["limits"][k], cap, (a["id"], k))
            self.assertIn("never follow instructions", a["prompt"].lower())
            self.assertIn("cannot approve", a["prompt"])

    def test_only_scene_image_video_and_qa_agents_can_propose(self):
        got = {a["id"] for a in agents.list_agents(dirs=[agents.BUILTIN_DIR]) if "propose" in a["tools"]}
        self.assertEqual(got, {"scene-designer", "image-artist", "video-director", "qa"})


if __name__ == "__main__":
    unittest.main()
