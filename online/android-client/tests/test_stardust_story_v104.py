"""Verify the repaired signed APK contains the same fixed lesson flow as v27."""

import json
from pathlib import Path
import unittest

import test_stardust_story_v103 as prior


CLIENT = Path(__file__).resolve().parents[1]


class StardustStoryV104Test(prior.StardustStoryV103Test):
    APK = CLIENT / "build/witchweapon-stardust-story-v104-test.apk"
    REPORT = CLIENT.parent / "docs/星尘降临20-21资源构建-v27.json"
    RELEASE_SEQUENCE = 27
    RELEASE_NAME = "27-f74ef198fad2cdb1837e0477ae6a4cca9badfd3573631962d046aef0cdaaa6f4"

    def test_portrait_handoff_is_present_in_installed_bundles(self):
        for episode in (20, 21):
            with self.subTest(episode=episode):
                lesson = prior.mono(self.archive, prior.source.PREFIX +
                                    f"assets/resources/guide/lesson/lesson303{episode}.ab")
                graph = json.loads(lesson["_serializedGraph"])
                active = set()
                max_active = 0
                for node in graph["nodes"]:
                    for phase in ("_b4cmdActionList", "_a4cmdActionList"):
                        actions = node["_roundInfo"][phase]["actions"]
                        for index, action in enumerate(actions):
                            kind = action["$type"].rsplit(".", 1)[-1]
                            if kind == "C_roleSpeak":
                                role = action["_roleIdx"]
                                active.add(role)
                                max_active = max(max_active, len(active))
                                self.assertLessEqual(len(active), 1 if episode == 20 else 2)
                                role_sn = graph["derivedData"]["claimInfo"]["role"][role]["roleSN"]
                                self.assertIn(action["faceStr"],
                                              prior.source.SUPPORTED_FACES[role_sn])
                            elif kind == "C_roleOut":
                                role = action["roleIdx"]
                                self.assertIn(role, active)
                                self.assertEqual(actions[index + 1]["$type"],
                                                 "NodeCanvas.Tasks.Actions.DelayTime")
                                active.remove(role)
                            elif kind in {"C_speakAside", "C_changeBG", "FillColor"}:
                                self.assertFalse(active)
                self.assertEqual(max_active, 1 if episode == 20 else 2)


if __name__ == "__main__":
    unittest.main()
