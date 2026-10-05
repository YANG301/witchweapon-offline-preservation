"""Static checks against the reviewed online v106 APK; no APK is written."""

from __future__ import annotations

import hashlib
import unittest
import zipfile

import UnityPy

import patch_local_mode_login_label as patch


class LocalModeLoginLabelTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        with zipfile.ZipFile(patch.SOURCE_APK) as apk:
            cls.source = {name: apk.read(name)
                          for name in (*patch.LOGIN_BUNDLES, patch.ASSET_INDEX)}
            cls.online_endpoint = apk.read("assets/online_endpoint.txt")
            cls.update_endpoint = apk.read("assets/update_endpoint.txt")

    def test_both_real_visitor_buttons_and_index_are_changed(self) -> None:
        for member, expected in patch.LOGIN_BUNDLES.items():
            self.assertEqual(hashlib.sha256(self.source[member]).hexdigest(), expected)
        self.assertEqual(hashlib.sha256(self.source[patch.ASSET_INDEX]).hexdigest(),
                         patch.ASSET_INDEX_SHA256)
        self.assertEqual(self.online_endpoint, b"https://212.192.15.11:18443\n")
        self.assertEqual(self.update_endpoint, b"https://212.192.15.11:18445\n")

        changed = patch.patch_login_assets(self.source)
        self.assertEqual(set(changed), {*patch.LOGIN_BUNDLES, patch.ASSET_INDEX})
        targets = {patch.LOGIN_PREFAB: patch.VISITOR_LABEL_COMPONENT,
                   patch.LOGIN_SCENE: 4442}
        for member, target_id in targets.items():
            old_objects = {(obj.assets_file.name, obj.path_id): obj.get_raw_data()
                           for obj in UnityPy.load(self.source[member]).objects}
            new_objects = {(obj.assets_file.name, obj.path_id): obj
                           for obj in UnityPy.load(changed[member]).objects}
            self.assertEqual(set(old_objects), set(new_objects))
            target = [(name, path_id) for name, path_id in new_objects
                      if path_id == target_id and
                      new_objects[(name, path_id)].type.name == "MonoBehaviour"]
            self.assertEqual(len(target), 1)
            self.assertEqual({key for key, obj in new_objects.items()
                              if obj.get_raw_data() != old_objects[key]},
                             set(target))
            self.assertEqual(new_objects[target[0]].read_typetree()["mText"], "本地模式")

        old_index = self.source[patch.ASSET_INDEX].decode("utf-8").splitlines()
        new_index = changed[patch.ASSET_INDEX].decode("utf-8").splitlines()
        self.assertEqual(len(old_index), len(new_index))
        changed_rows = [(before, after) for before, after in zip(old_index, new_index)
                        if before != after]
        self.assertEqual(len(changed_rows), 2)
        for member in patch.LOGIN_BUNDLES:
            index_name = "/" + member.removeprefix("assets/assetbundle/")
            expected = (hashlib.md5(changed[member]).hexdigest() + "=" + index_name
                        + ":" + str(len(changed[member])))
            self.assertEqual(new_index.count(expected), 1)

    def test_unreviewed_or_incomplete_inputs_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            patch.patch_login_assets({patch.LOGIN_PREFAB: self.source[patch.LOGIN_PREFAB]})
        for member in patch.LOGIN_BUNDLES:
            altered = bytearray(self.source[member])
            altered[-1] ^= 1
            with self.assertRaises(ValueError):
                (patch.patch_login_prefab if member == patch.LOGIN_PREFAB
                 else patch.patch_login_scene)(bytes(altered))


if __name__ == "__main__":
    unittest.main()
