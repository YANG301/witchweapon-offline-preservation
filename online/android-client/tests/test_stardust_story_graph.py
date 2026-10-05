"""Guard the original conversation player's single portrait slot contract."""

import ast
import hashlib
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import zipfile

import UnityPy


CLIENT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CLIENT))
import restore_stardust_20_21 as story  # noqa: E402


class StardustStoryGraphTest(unittest.TestCase):
    def test_action_flow_matches_the_existing_nineteenth_episode(self):
        reference = story.SCRIPT / "stardustdescends_ep19.gd"
        raw = reference.read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(),
                         "70807234ad0db01c66741fc33bff8a49f9dc1538e51b495668abd0b10ee17237")
        events = []
        for line in raw.decode("utf-8-sig").splitlines():
            match = story.EVENT.match(line)
            if match is None:
                continue
            values = ast.parse("f(" + match.group(2) + ")", mode="eval").body.args
            args = [ast.literal_eval(value) for value in values]
            if match.group(1) in {"show_character", "show_2nd_character"} and len(args) == 1:
                args.append("normal")
            events.append((match.group(1), args))
        with zipfile.ZipFile(story.APK) as archive:
            bundle = UnityPy.load(archive.read(story.LESSON_TEMPLATE))
            original = json.loads(next(obj.read_typetree()["_serializedGraph"]
                                       for obj in bundle.objects
                                       if obj.type.name == "MonoBehaviour"))
        extra_music = {Path(args[0]).stem: 0 for kind, args in events
                       if kind == "change_music" and Path(args[0]).stem not in story.BGM_IDS}
        with patch.dict(story.CHARACTER_NAME,
                        {"akiko": "秋子", "akikounglass": "秋子", "hamon": "哈蒙"}), \
                patch.dict(story.BGM_IDS, extra_music):
            recreated, _, _ = story.graph_from_events(original, 19, events)

        def action_flow(graph):
            result = {}
            for node in graph["nodes"]:
                actions = node["_roundInfo"]["_b4cmdActionList"]["actions"]
                spoken = [item for item in actions if item["$type"].endswith(
                    ("C_roleSpeak", "C_speakAside"))]
                if spoken and spoken[-1].get("sentenceIdx", -1) >= 0:
                    result[spoken[-1]["sentenceIdx"]] = [
                        item["$type"].rsplit(".", 1)[-1] for item in actions
                        if not item["$type"].endswith(("PlayBGM", "StopBGM"))]
            return result

        self.assertEqual(len(action_flow(original)), 349)
        self.assertEqual(action_flow(recreated), action_flow(original))

    def test_named_offscreen_dialogue_uses_original_aside_action(self):
        with zipfile.ZipFile(story.APK) as archive:
            bundle = UnityPy.load(archive.read(story.LESSON_TEMPLATE))
            template = json.loads(next(obj.read_typetree()["_serializedGraph"]
                                       for obj in bundle.objects
                                       if obj.type.name == "MonoBehaviour"))
        for episode, offscreen_lines in ((20, (13, 16, 17)), (21, (38, 178, 179))):
            with self.subTest(episode=episode):
                graph, _, _ = story.graph_from_events(
                    template, episode, story.source_events(episode))
                for index in offscreen_lines:
                    actions = graph["nodes"][index]["_roundInfo"]["_b4cmdActionList"]["actions"]
                    self.assertEqual(actions[-1]["$type"],
                                     "NodeCanvas.Tasks.Actions.C_speakAside")
                    self.assertTrue(actions[-1]["spName"])

    def test_portrait_exits_before_another_speaker_or_aside(self):
        with zipfile.ZipFile(story.APK) as archive:
            bundle = UnityPy.load(archive.read(story.LESSON_TEMPLATE))
            template = json.loads(next(obj.read_typetree()["_serializedGraph"]
                                       for obj in bundle.objects
                                       if obj.type.name == "MonoBehaviour"))
        for episode in (20, 21):
            with self.subTest(episode=episode):
                graph, sentences, _ = story.graph_from_events(
                    template, episode, story.source_events(episode))
                self.assertEqual(len(graph["nodes"]), len(sentences))
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
                                self.assertLessEqual(len(active), 1 if episode == 20 else 2,
                                                     (episode, node["$id"], active))
                                role_sn = graph["derivedData"]["claimInfo"]["role"][role]["roleSN"]
                                self.assertIn(action["faceStr"],
                                              story.SUPPORTED_FACES[role_sn])
                            elif kind == "C_roleOut":
                                role = action["roleIdx"]
                                self.assertIn(role, active)
                                self.assertLess(index + 1, len(actions))
                                self.assertEqual(actions[index + 1]["$type"],
                                                 "NodeCanvas.Tasks.Actions.DelayTime")
                                self.assertEqual(actions[index + 1]["delaytime"], 0.5)
                                active.remove(role)
                            elif kind in {"C_speakAside", "C_changeBG", "FillColor"}:
                                self.assertFalse(active, (episode, node["$id"], kind, active))
                self.assertEqual(max_active, 1 if episode == 20 else 2)


if __name__ == "__main__":
    unittest.main()
