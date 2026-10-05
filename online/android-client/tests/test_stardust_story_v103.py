"""Check the client-facing contracts across the restored story bundles."""

import hashlib
import json
from pathlib import Path
import sys
import unittest
import zipfile

import UnityPy


HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
import restore_stardust_20_21 as source  # noqa: E402


APK = HERE / "build/witchweapon-stardust-story-v103-test.apk"


def mono(archive, member):
    return next(obj.read_typetree() for obj in UnityPy.load(archive.read(member)).objects
                if obj.type.name == "MonoBehaviour")


def table(archive, member):
    return bytes(byte ^ 255 for byte in mono(archive, member)["bytes"]).decode("utf-8-sig")


class StardustStoryV103Test(unittest.TestCase):
    APK = APK
    REPORT = source.REPORT
    RELEASE_SEQUENCE = 25
    RELEASE_NAME = None

    @classmethod
    def setUpClass(cls):
        cls.archive = zipfile.ZipFile(cls.APK)
        cls.report = json.loads(cls.REPORT.read_text(encoding="utf-8"))

    @classmethod
    def tearDownClass(cls):
        cls.archive.close()

    def test_each_story_node_has_matching_sentence_and_background(self):
        for episode, count in ((20, 341), (21, 196)):
            with self.subTest(episode=episode):
                lesson = mono(self.archive, source.PREFIX +
                              f"assets/resources/guide/lesson/lesson303{episode}.ab")
                sentences = table(self.archive, source.PREFIX +
                                  f"config/lesson/sentence_303{episode}.ab").splitlines()
                graph = json.loads(lesson["_serializedGraph"])
                self.assertEqual(lesson["m_Name"], f"lesson303{episode}")
                self.assertEqual(lesson["sentenceFileName"], f"sentence_303{episode}.txt")
                self.assertEqual(len(sentences), count)
                self.assertEqual(len(graph["nodes"]), count)
                self.assertEqual(len(graph["connections"]), count - 1)
                roles = graph["derivedData"]["claimInfo"]["role"]
                used_backgrounds = set()
                for index, node in enumerate(graph["nodes"]):
                    actions = node["_roundInfo"]["_b4cmdActionList"]["actions"]
                    speech = [item for item in actions if item["$type"].endswith(
                        ("C_roleSpeak", "C_speakAside"))]
                    self.assertEqual(len(speech), 1)
                    self.assertEqual(speech[0]["sentenceIdx"], index)
                    row = sentences[index].split("\t")
                    self.assertEqual(int(row[0]), index + 1)
                    self.assertEqual(speech[0]["wordStr"], row[2])
                    if "_roleIdx" in speech[0]:
                        self.assertLess(speech[0]["_roleIdx"], len(roles))
                    used_backgrounds.update(item["picName"] for item in actions
                                            if item["$type"].endswith("C_changeBG"))
                self.assertEqual(used_backgrounds,
                                 set(self.report["chapters"][str(episode)]["backgrounds"]))
                for name in used_backgrounds:
                    self.assertIn(source.background_member(name), self.archive.namelist())
                ending = graph["nodes"][-1]["_roundInfo"]["_a4cmdActionList"]["actions"]
                self.assertTrue(any(a["$type"].endswith("EndLesson") for a in ending))

    def test_story_catalog_and_index_reference_all_new_bundles(self):
        release_folder = HERE.parent / "热更新测试/主线热更候选/releases"
        release = (release_folder / self.RELEASE_NAME / "manifest.json"
                   if self.RELEASE_NAME else
                   next(release_folder.glob(f"{self.RELEASE_SEQUENCE}-*/manifest.json")))
        manifest = json.loads(release.read_text(encoding="utf-8"))
        self.assertEqual(manifest["targetAppVersion"],
                         self.archive.read("assets/m.version").decode("ascii").strip())
        signed_assets = {item["path"]: item["sha256"] for item in manifest["assets"]}
        rows = [line.split(",") for line in table(self.archive, source.STORY_TABLE).splitlines()]
        for episode in (20, 21):
            with self.subTest(episode=episode):
                target = [row for row in rows if row[:2] ==
                          [f"613000410{episode}", "25"]]
                self.assertEqual(len(target), 1)
                self.assertEqual(target[0][4:6], [f"303{episode}", "1"])
                self.assertEqual(target[0][-1], "1")
        dictionary = table(self.archive, source.DICTIONARY_TABLE)
        for episode in (20, 21):
            self.assertIn(f"1613000410{episode}01\t第{episode}节\t", dictionary)
        index = self.archive.read(source.INDEX).decode("utf-8").splitlines()
        for logical, info in self.report["assets"].items():
            member = "assets/" + logical
            data = self.archive.read(member)
            self.assertEqual(hashlib.sha256(data).hexdigest(), info["sha256"])
            self.assertEqual(signed_assets[logical], info["sha256"])
            key = "/" + logical.removeprefix("assetbundle/")
            expected = f"{hashlib.md5(data).hexdigest()}={key}:{len(data)}"
            self.assertEqual(index.count(expected), 1)


if __name__ == "__main__":
    unittest.main()
