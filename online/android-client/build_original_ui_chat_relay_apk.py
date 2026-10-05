"""Build a separate original-UI chat relay test APK from the pinned v3 APK.

Original level gates and Unity controls remain unchanged. Only the two CN
router URLs, their bundle index, and the Android adapter DEX are replaced.
"""

import argparse
import copy
import json
import os
from pathlib import Path
import zipfile

import UnityPy

import build_online_apk as adapter
import build_original_ui_xinfengzhou_apk as base
import probe_original_chat_assets as probe


HERE = Path(__file__).resolve().parent
OUTPUT = HERE / "build"
SOURCE = OUTPUT / "witchweapon-online-original-ui-chat-rtm-probe-v3-test.apk"
SOURCE_SHA256 = "611953d0da0759f5c0e0b53d9275f9e970935153e74337591d6bc34524fc66ca"
RESULT = OUTPUT / "witchweapon-online-original-ui-chat-relay-v5-test.apk"
REPORT = OUTPUT / "原版聊天正式回环候选包验收.json"
TEMP = Path(r"D:\Environment\Android\temp\witch-online-chat-relay-v5")
BUNDLE = probe.BUNDLE
INDEX = probe.INDEX
DEX = "classes2.dex"
FIXTURES = probe.FIXTURES
CHANGED = {BUNDLE, INDEX, DEX}
OLD_ROUTER = "URL_CN_LEANCLOUD_RTMRouter,http://127.0.0.1:18301,CN"
OLD_ENGINE = "URL_CN_LEANCLOUD_EngineServer,http://127.0.0.1:18301,CN"
NEW_ROUTER = "URL_CN_LEANCLOUD_RTMRouter,http://127.0.0.1:19878,CN"
NEW_ENGINE = "URL_CN_LEANCLOUD_EngineServer,http://127.0.0.1:19878,CN"
TOOLS = Path(r"D:\Environment\Android\build-tools\35.0.0")
JAVA = Path(r"D:\Environment\AndroidReverse\jadx-1.5.6\jre\bin\java.exe")
KEY = Path(r"D:\Project\魔女兵器工程恢复\单机版\作者源码构建\author-local-test.jks")


def patch_router(raw):
    env = UnityPy.load(raw)
    objects = [item for item in env.objects if item.type.name == "MonoBehaviour"]
    if len(objects) != 1:
        raise ValueError("Expected one ClientPlatformConstant MonoBehaviour")
    item = objects[0]
    tree = item.read_typetree()
    if tree.get("isEncrypt") != 1 or not isinstance(tree.get("bytes"), list):
        raise ValueError("Unexpected encrypted router bundle")
    original = bytes(byte ^ 255 for byte in tree["bytes"]).decode("utf-8-sig")
    lines = original.splitlines(keepends=True)
    plain = [line.rstrip("\r\n") for line in lines]
    if len(plain) < 27 or plain.count(OLD_ROUTER) != 1 or plain.count(OLD_ENGINE) != 1:
        raise ValueError("Pinned v3 router/engine rows differ")
    for index, before in enumerate(plain):
        if before == OLD_ROUTER:
            lines[index] = lines[index].replace(OLD_ROUTER, NEW_ROUTER)
        elif before == OLD_ENGINE:
            lines[index] = lines[index].replace(OLD_ENGINE, NEW_ENGINE)
    replacement = "".join(lines)
    if len(replacement.splitlines()) != len(original.splitlines()):
        raise ValueError("Router CSV row count changed")
    for before, after in zip(original.splitlines(), replacement.splitlines()):
        if before != after and (before, after) not in (
                (OLD_ROUTER, NEW_ROUTER), (OLD_ENGINE, NEW_ENGINE)):
            raise ValueError("Unrelated router CSV row changed")
    tree["bytes"] = list(bytes(byte ^ 255 for byte in ("\ufeff" + replacement).encode("utf-8")))
    item.save_typetree(tree)
    modified = env.file.save(packer="original")
    verify = UnityPy.load(modified)
    read_tree = next(obj.read_typetree() for obj in verify.objects if obj.type.name == "MonoBehaviour")
    readback = bytes(byte ^ 255 for byte in read_tree["bytes"]).decode("utf-8-sig")
    if readback != replacement or read_tree.get("isEncrypt") != 1:
        raise ValueError("Router bundle readback failed")
    return modified


def prepare():
    if not SOURCE.is_file() or base.sha256(SOURCE) != SOURCE_SHA256:
        raise ValueError("Pinned v3 APK is missing or changed")
    for path in (JAVA, KEY, TOOLS / "zipalign.exe", TOOLS / "lib/apksigner.jar"):
        if not path.is_file():
            raise ValueError("Portable Android build dependency missing: " + str(path))
    with zipfile.ZipFile(SOURCE) as apk:
        names = apk.namelist()
        if len(names) != len(set(names)) or not {BUNDLE, INDEX, DEX, FIXTURES}.issubset(names):
            raise ValueError("Pinned v3 APK members invalid")
        old_bundle = apk.read(BUNDLE)
        old_index = apk.read(INDEX)
        old_dex = apk.read(DEX)
        fixture = json.loads(apk.read(FIXTURES).decode("utf-8"))
    values = probe.decode_ids(__import__("base64").b64decode(
        fixture[probe.ROUTE]["base64"]))
    if values != {1: "xinfengzhou-world", 2: "xinfengzhou-system",
                   3: "xinfengzhou-notify"}:
        raise ValueError("Pinned original UI conversation IDs changed")
    bundle = patch_router(old_bundle)
    index = adapter.patch_index(old_index, {"/config/clientexel/clientplatformconstant.ab": bundle})
    files, original_classes, _ = adapter.check_inputs()
    dex, compiled = adapter.compile_dex(files, original_classes)
    existing_classes = set(adapter.dex_classes(old_dex))
    built_classes = set(compiled)
    added = built_classes - existing_classes
    expected = {"Lcom/codex/witchweapon/ChatWebSocketRelay;",
                "Lcom/codex/witchweapon/ChatWebSocketRelay$1;"}
    if existing_classes - built_classes or added != expected:
        raise ValueError("Unexpected Android adapter class change")
    if bundle == old_bundle or index == old_index or dex == old_dex:
        raise ValueError("One expected chat relay payload did not change")
    return {BUNDLE: bundle, INDEX: index, DEX: dex}, len(existing_classes), len(built_classes)


def verify(path, prepared):
    with zipfile.ZipFile(SOURCE) as old, zipfile.ZipFile(path) as new:
        old_names = {name for name in old.namelist() if not base.SIGNATURE.fullmatch(name)}
        new_names = {name for name in new.namelist() if not base.SIGNATURE.fullmatch(name)}
        if old_names != new_names or len(new.namelist()) != len(set(new.namelist())):
            raise ValueError("Unexpected APK members")
        for name in CHANGED:
            if new.read(name) != prepared[name]:
                raise ValueError("Signed APK lost changed member: " + name)
        unchanged = 0
        for name in sorted(old_names - CHANGED):
            with old.open(name) as before, new.open(name) as after:
                if base.stream_digest(before) != base.stream_digest(after):
                    raise ValueError("Unrelated APK member changed: " + name)
            unchanged += 1
        if old.read("AndroidManifest.xml") != new.read("AndroidManifest.xml"):
            raise ValueError("Original launcher/manifest changed")
        if old.read(FIXTURES) != new.read(FIXTURES):
            raise ValueError("Conversation ID fixture changed")
    if base.sha256(SOURCE) != SOURCE_SHA256:
        raise ValueError("Pinned v3 APK changed during build")
    return unchanged


def build(prepared, old_classes, new_classes):
    unsigned = OUTPUT / "chat-relay-v5-unsigned.apk"
    aligned = OUTPUT / "chat-relay-v5-aligned.apk"
    candidate = OUTPUT / "chat-relay-v5-candidate.next.apk"
    staged_report = OUTPUT / "chat-relay-v5-report.next.json"
    sidecar = Path(str(candidate) + ".idsig")
    for path in (RESULT, REPORT, unsigned, aligned, candidate, staged_report, sidecar):
        if path.exists():
            raise ValueError("Versioned v5 output/intermediate already exists: " + str(path))
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
        "originalChatLevelGatesPreserved": True,
        "conversationIdsPreserved": True,
        "localRouterOrigin": "http://127.0.0.1:19878",
        "localWebSocketPath": "/rtm?subprotocol=lc.json.3",
        "gatewayPath": "/api/v1/chat/rtm",
        "adapterClassesBefore": old_classes,
        "adapterClassesAfter": new_classes,
        "changedPayloadMembers": sorted(CHANGED),
        "verifiedUnchangedPayloadMembers": unchanged,
        "signatureVerification": signature,
        "alignmentVerification": alignment,
        "notInstalled": True,
        "chatEndToEndTested": False,
        "publicUseAllowed": False,
        "securityLimit": "Android loopback TCP is reachable by other apps until same-UID proof is added",
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
    prepared, old_classes, new_classes = prepare()
    if args.check:
        print(json.dumps({"status": "in_memory_check_ok", "source": str(SOURCE),
                          "changedPayloadMembers": sorted(CHANGED),
                          "adapterClassesBefore": old_classes,
                          "adapterClassesAfter": new_classes, "apkCreated": False},
                         ensure_ascii=False, indent=2))
    else:
        print(json.dumps(build(prepared, old_classes, new_classes), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
