"""Rebuild the final task marker APK directly from the installed 20043085 base.

Apply the two reviewed Lua edits in order so the intermediate 20043086 APK
is not needed for future reproduction.
"""

from pathlib import Path

import build_visible_hotupdate_v8_apk as build
import patch_visible_hotupdate_v8 as email_patch
import patch_visible_task_hotupdate_v9 as task_patch


base_manifest_patch = build.patch_android_manifest


class CombinedPatch:
    MEMBER = task_patch.MEMBER

    @staticmethod
    def patch(raw: bytes) -> bytes:
        return task_patch.patch(email_patch.patch(raw))


def version_chain(raw: bytes) -> bytes:
    intermediate = base_manifest_patch(
        raw, old_code=20043085, new_code=20043086,
        old_name="2.0.1.20043085", new_name="2.0.1.20043086")
    return base_manifest_patch(
        intermediate, old_code=20043086, new_code=20043087,
        old_name="2.0.1.20043086", new_name="2.0.1.20043087")


build.patch_android_manifest = version_chain
build.SOURCE = Path(r"D:\Project\魔女兵器在线版\android-client\build\历史发布包\魔女兵器-online.apk")
build.SOURCE_SHA256 = "39f6285818fe2d7076f4b99803d18d1d20ad41659955359b5df100b355f65a92"
build.OUTPUT = Path(r"D:\Project\魔女兵器在线版\android-client\build\历史发布包\魔女兵器-新丰洲-热更9同步版.apk")
build.REPORT = build.OUTPUT.with_suffix(".json")
build.TEMP = Path(r"D:\Environment\Android\temp\witch-visible-hotupdate-v9")
build.OLD_CODE = 20043085
build.NEW_CODE = 20043087
build.OLD_NAME = "2.0.1.20043085"
build.NEW_NAME = "2.0.1.20043087"
build.VISIBLE_CHANGE = "任务计数前显示热更9标记"
build.visible = CombinedPatch


if __name__ == "__main__":
    build.main()
