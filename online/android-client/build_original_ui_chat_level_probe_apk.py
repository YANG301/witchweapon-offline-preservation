"""Build an isolated v4 APK to inspect the original Lv.5 chat controls.

Only the android_taptap:25 visibility/speech gates change from 15/20 to 1.
The original UI and the v3 loopback RTM protocol probe remain untouched.
"""

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import zipfile

import UnityPy

import build_original_ui_xinfengzhou_apk as base
import probe_original_chat_assets as probe


HERE = Path(__file__).resolve().parent
OUTPUT = HERE / "build"
SOURCE = OUTPUT / "witchweapon-online-original-ui-chat-rtm-probe-v3-test.apk"
SOURCE_SHA256 = "611953d0da0759f5c0e0b53d9275f9e970935153e74337591d6bc34524fc66ca"
RESULT = OUTPUT / "witchweapon-online-original-ui-chat-level-probe-v4-test.apk"
REPORT = OUTPUT / "原版聊天等级回环诊断包验收.json"
TEMP = Path(r"D:\Environment\Android\temp\witch-online-chat-level-probe-v4")
BUNDLE = "assets/assetbundle/config/clientexel/constant.ab"
INDEX = probe.INDEX
CHANGED = {BUNDLE, INDEX}
OLD_SPEAK = "CHAT_SPEAK_LEVEL,,,20,,25,,,,,,"
OLD_SEE = "CHAT_CAN_SEE_LEVEL,,,15,,25,,,,,,"
NEW_SPEAK = "CHAT_SPEAK_LEVEL,,,1,,25,,,,,,"
NEW_SEE = "CHAT_CAN_SEE_LEVEL,,,1,,25,,,,,,"
TOOLS = Path(r"D:\Environment\Android\build-tools\35.0.0")
JAVA = Path(r"D:\Environment\AndroidReverse\jadx-1.5.6\jre\bin\java.exe")
KEY = Path(r"D:\Project\魔女兵器工程恢复\单机版\作者源码构建\author-local-test.jks")


def patch_bundle(raw):
    env = UnityPy.load(raw)
    objects = [item for item in env.objects if item.type.name == "MonoBehaviour"]
    if len(objects) != 1:
        raise ValueError("Expected one Constant MonoBehaviour")
    item = objects[0]
    tree = item.read_typetree()
    if tree.get("isEncrypt") != 1 or not isinstance(tree.get("bytes"), list):
        raise ValueError("Unexpected Constant serialization")
    text = bytes(byte ^ 255 for byte in tree["bytes"]).decode("utf-8-sig")
    lines = text.splitlines(keepends=True)
    old_lines = [line.rstrip("\r\n") for line in lines]
    if old_lines.count(OLD_SPEAK) != 1 or old_lines.count(OLD_SEE) != 1:
        raise ValueError("Current android_taptap:25 chat gates differ from reviewed source")
    for index, line in enumerate(lines):
        if old_lines[index] == OLD_SPEAK:
            lines[index] = line.replace(OLD_SPEAK, NEW_SPEAK)
        elif old_lines[index] == OLD_SEE:
            lines[index] = line.replace(OLD_SEE, NEW_SEE)
    replacement = "".join(lines)
    if len(replacement.splitlines()) != len(text.splitlines()):
        raise ValueError("Constant CSV row count changed")
    for before, after in zip(text.splitlines(), replacement.splitlines()):
        if before != after and (before, after) not in ((OLD_SPEAK, NEW_SPEAK), (OLD_SEE, NEW_SEE)):
            raise ValueError("Unrelated Constant CSV row changed")
    tree["bytes"] = list(bytes(byte ^ 255 for byte in ("\ufeff" + replacement).encode("utf-8")))
    item.save_typetree(tree)
    result = env.file.save(packer="original")
    read_env = UnityPy.load(result)
    read_tree = next(obj.read_typetree() for obj in read_env.objects if obj.type.name == "MonoBehaviour")
    readback = bytes(byte ^ 255 for byte in read_tree["bytes"]).decode("utf-8-sig")
    if readback != replacement or read_tree.get("isEncrypt") != 1:
        raise ValueError("Constant bundle round-trip failed")
    return result


def prepare():
    if not SOURCE.is_file() or base.sha256(SOURCE) != SOURCE_SHA256:
        raise ValueError("Pinned v3 APK is missing or changed")
    for path in (JAVA, KEY, TOOLS / "zipalign.exe", TOOLS / "lib/apksigner.jar"):
        if not path.is_file():
            raise ValueError("Portable APK signing tool missing: " + str(path))
    with zipfile.ZipFile(SOURCE) as apk:
        if len(apk.namelist()) != len(set(apk.namelist())) or not CHANGED.issubset(apk.namelist()):
            raise ValueError("Pinned v3 APK members invalid")
        old_bundle = apk.read(BUNDLE)
        old_index = apk.read(INDEX)
    bundle = patch_bundle(old_bundle)
    index = probe.base.patch_index(old_index, {"/config/clientexel/constant.ab": bundle})
    if bundle == old_bundle or index == old_index:
        raise ValueError("Chat level bundle or index did not change")
    return {BUNDLE: bundle, INDEX: index}


def verify(path, prepared):
    with zipfile.ZipFile(SOURCE) as old, zipfile.ZipFile(path) as new:
        old_names = {name for name in old.namelist() if not base.SIGNATURE.fullmatch(name)}
        new_names = {name for name in new.namelist() if not base.SIGNATURE.fullmatch(name)}
        if old_names != new_names or len(new.namelist()) != len(set(new.namelist())):
            raise ValueError("Unexpected signed APK members")
        if any(new.read(name) != prepared[name] for name in CHANGED):
            raise ValueError("Patched constant bytes differ in signed APK")
        unchanged = 0
        for name in sorted(old_names - CHANGED):
            with old.open(name) as before, new.open(name) as after:
                if base.stream_digest(before) != base.stream_digest(after):
                    raise ValueError("Unrelated APK payload changed: " + name)
            unchanged += 1
        if old.read("AndroidManifest.xml") != new.read("AndroidManifest.xml"):
            raise ValueError("Android launcher/manifest changed")
    if base.sha256(SOURCE) != SOURCE_SHA256:
        raise ValueError("Pinned v3 APK changed during build")
    return unchanged


def build(prepared):
    unsigned = OUTPUT / "chat-level-probe-v4-unsigned.apk"
    aligned = OUTPUT / "chat-level-probe-v4-aligned.apk"
    candidate = OUTPUT / "chat-level-probe-v4-candidate.next.apk"
    staged_report = OUTPUT / "chat-level-probe-v4-report.next.json"
    sidecar = Path(str(candidate) + ".idsig")
    for path in (RESULT, REPORT, unsigned, aligned, candidate, staged_report, sidecar):
        if path.exists():
            raise ValueError("Versioned v4 output/intermediate already exists: " + str(path))
    TEMP.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(SOURCE) as old, zipfile.ZipFile(unsigned, "x", allowZip64=False) as new:
        for info in old.infolist():
            if base.SIGNATURE.fullmatch(info.filename):
                continue
            if info.filename in prepared:
                new.writestr(copy.copy(info), prepared[info.filename])
            else:
                base.copy_compressed_entry(old, new, info)
    base.run([TOOLS / "zipalign.exe", "-p", "4", unsigned, aligned])
    env = os.environ.copy()
    env["TEMP"] = str(TEMP)
    env["TMP"] = str(TEMP)
    env["WITCH_TEST_KEYPASS"] = "local-stage1"
    signer = [JAVA, "-jar", TOOLS / "lib/apksigner.jar"]
    base.run([*signer, "sign", "--ks", KEY, "--ks-key-alias", "local",
              "--ks-pass", "env:WITCH_TEST_KEYPASS", "--key-pass", "env:WITCH_TEST_KEYPASS",
              "--out", candidate, aligned], env)
    signature = base.run([*signer, "verify", "--verbose", "--print-certs", candidate], env)
    alignment = base.run([TOOLS / "zipalign.exe", "-c", "-p", "4", candidate])
    unchanged = verify(candidate, prepared)
    report = {
        "status": "signed_static_validation_only",
        "source": base.record(SOURCE),
        "testApk": {"path": str(RESULT), "bytes": candidate.stat().st_size,
                    "sha256": base.sha256(candidate)},
        "originalPackageAndLauncherPreserved": True,
        "channelGroup": 25,
        "chatCanSeeLevel": {"before": 15, "after": 1},
        "chatSpeakLevel": {"before": 20, "after": 1},
        "changedPayloadMembers": sorted(CHANGED),
        "verifiedUnchangedPayloadMembers": unchanged,
        "signatureVerification": signature,
        "alignmentVerification": alignment,
        "notInstalled": True,
        "chatUiRuntimeTested": False,
        "publicUseAllowed": False,
    }
    staged_report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    candidate.rename(RESULT)
    staged_report.rename(REPORT)
    unsigned.unlink()
    aligned.unlink()
    if sidecar.exists():
        sidecar.unlink()
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--build", action="store_true")
    args = parser.parse_args()
    if args.check == args.build:
        parser.error("choose exactly one of --check or --build")
    prepared = prepare()
    if args.check:
        print(json.dumps({"status": "in_memory_check_ok", "source": str(SOURCE),
                          "changedPayloadMembers": sorted(CHANGED), "apkCreated": False},
                         ensure_ascii=False, indent=2))
    else:
        print(json.dumps(build(prepared), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
