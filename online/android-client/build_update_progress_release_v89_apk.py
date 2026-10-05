"""Synchronize the signed progress-demo release into the future full APK."""

from pathlib import Path

import build_visible_hotupdate_v8_apk as build
import patch_update_progress_delivery_v10 as delivery


build.SOURCE = Path(r"D:\Project\魔女兵器在线版\android-client\build\witchweapon-update-progress-v88-test.apk")
build.SOURCE_SHA256 = "e60dc9e3eeb3a24d8ad27238abd8f592a1f515e201690f5a5990cf4b82ca94f0"
build.OUTPUT = Path(r"D:\Project\魔女兵器在线版\更新版\魔女兵器-新丰洲-更新进度版.apk")
build.REPORT = build.OUTPUT.with_suffix(".json")
build.TEMP = Path(r"D:\Environment\Android\temp\witch-loader-progress-v89")
build.OLD_CODE = 20043088
build.NEW_CODE = 20043089
build.OLD_NAME = "2.0.1.20043088"
build.NEW_NAME = "2.0.1.20043089"
build.VISIBLE_CHANGE = "原版加载画面叠加真实资源下载进度；移除热更测试标记"
build.visible = delivery


if __name__ == "__main__":
    build.main()
