"""Validate an isolated asset-only path for the original UIChat's RTM startup.

This program does not create an APK, contact the legacy LeanCloud project, or
change any files. It prepares the exact two candidate payload members in memory
and reloads their Unity/protobuf formats. A later versioned APK build may use
the same transformations after the RTM server and authentication are reviewed.
"""

import argparse
import base64
import hashlib
import json
import re
import zipfile
from pathlib import Path
from urllib.parse import urlsplit

import UnityPy

import build_online_apk as base


APK = Path(__file__).resolve().parent / "build" / "witchweapon-online-original-ui-xinfengzhou-hide-white-v2-test.apk"
APK_SHA256 = "aa8cc71522c472202bf3e5052871c323d4b39cce8107d052531d13a08719166a"
BUNDLE = "assets/assetbundle/config/clientexel/clientplatformconstant.ab"
INDEX = "assets/m.assets_list.txt"
FIXTURES = "assets/offline_responses.json"
ROUTE = "/misc/getLeancloudInfo"
OLD_ROUTER = "URL_CN_LEANCLOUD_RTMRouter,https://router-g0-push.avoscloud.com,CN"
OLD_ENGINE = "URL_CN_LEANCLOUD_EngineServer,https://avoscloud.com,CN"


def validate_origin(value):
    parts = urlsplit(value)
    local_probe = parts.scheme == "http" and parts.hostname == "127.0.0.1" and parts.port is not None
    if (not (parts.scheme == "https" or local_probe) or not parts.hostname or parts.path or parts.query
            or parts.fragment or parts.username or parts.password or value.endswith("/")):
        raise ValueError("chat origin must be HTTPS or Android loopback HTTP for isolated testing")
    try:
        port = parts.port
    except ValueError as failed:
        raise ValueError("invalid chat origin port") from failed
    if port is not None and not (1 <= port <= 65535):
        raise ValueError("invalid chat origin port")
    return value


def validate_id(value):
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,96}", value):
        raise ValueError("conversation IDs must be 1-96 URL-safe ASCII characters")
    return value


def field(number, value):
    encoded = value.encode("ascii")
    if len(encoded) >= 128:
        raise ValueError("conversation ID too long")
    return bytes((number << 3 | 2, len(encoded))) + encoded


def decode_ids(payload):
    fields = {}
    cursor = 0
    while cursor < len(payload):
        tag = payload[cursor]
        length = payload[cursor + 1]
        cursor += 2
        fields[tag >> 3] = payload[cursor:cursor + length].decode("ascii")
        cursor += length
    if cursor != len(payload) or set(fields) != {1, 2, 3}:
        raise ValueError("invalid Leancloud protobuf")
    return fields


def patch_bundle(raw, origin):
    env = UnityPy.load(raw)
    objects = [item for item in env.objects if item.type.name == "MonoBehaviour"]
    if len(objects) != 1:
        raise ValueError("expected one ClientPlatformConstant MonoBehaviour")
    item = objects[0]
    tree = item.read_typetree()
    if tree.get("isEncrypt") != 1 or not isinstance(tree.get("bytes"), list):
        raise ValueError("unexpected ClientPlatformConstant serialization")
    original = bytes(byte ^ 255 for byte in tree["bytes"]).decode("utf-8-sig")
    lines = original.splitlines(keepends=True)
    if (len(lines) < 27 or lines[15].rstrip("\r\n") != OLD_ENGINE
            or lines[19].rstrip("\r\n") != OLD_ROUTER
            or lines[23].rstrip("\r\n") != "URL_CN_LEANCLOUD_RTMRouter_OPEN,1,CN"):
        raise ValueError("original CN LeanCloud route is not at the reviewed rows")
    lines[15] = lines[15].replace("https://avoscloud.com", origin)
    lines[19] = lines[19].replace("https://router-g0-push.avoscloud.com", origin)
    replacement = "".join(lines)
    if replacement == original:
        raise ValueError("chat route did not change")
    tree["bytes"] = list(bytes(byte ^ 255 for byte in ("\ufeff" + replacement).encode("utf-8")))
    item.save_typetree(tree)
    modified = env.file.save(packer="original")
    verify = UnityPy.load(modified)
    verify_tree = next(obj.read_typetree() for obj in verify.objects if obj.type.name == "MonoBehaviour")
    readback = bytes(byte ^ 255 for byte in verify_tree["bytes"]).decode("utf-8-sig")
    if readback != replacement or verify_tree.get("isEncrypt") != 1:
        raise ValueError("chat route bundle round-trip failed")
    for before, after in zip(original.splitlines(), readback.splitlines()):
        if before != after and before not in (OLD_ROUTER, OLD_ENGINE):
            raise ValueError("unrelated ClientPlatformConstant row changed")
    return modified


def patch_fixture(raw, ids):
    original = json.loads(raw.decode("utf-8"))
    if original.get(ROUTE) != {"type": "application/octet-stream", "base64": ""}:
        raise ValueError("unexpected empty Leancloud fixture")
    payload = b"".join(field(number, ids[number]) for number in (1, 2, 3))
    encoded = base64.b64encode(payload).decode("ascii")
    pattern = rb'("/misc/getLeancloudInfo"\s*:\s*\{\s*"type"\s*:\s*"application/octet-stream"\s*,\s*"base64"\s*:\s*)""'
    if len(re.findall(pattern, raw)) != 1:
        raise ValueError("Leancloud fixture is not uniquely located")
    modified = re.sub(pattern, lambda match: match.group(1) + b'"' + encoded.encode("ascii") + b'"', raw)
    readback = json.loads(modified.decode("utf-8"))
    for route, item in original.items():
        if route != ROUTE and readback.get(route) != item:
            raise ValueError("unrelated fixture changed: " + route)
    if set(readback) != set(original) or decode_ids(base64.b64decode(readback[ROUTE]["base64"])) != ids:
        raise ValueError("Leancloud protobuf round-trip failed")
    return modified


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--origin", default="http://127.0.0.1:18301")
    parser.add_argument("--world-id", default="xinfengzhou-world")
    parser.add_argument("--system-id", default="xinfengzhou-system")
    parser.add_argument("--notify-id", default="xinfengzhou-notify")
    args = parser.parse_args()
    origin = validate_origin(args.origin)
    ids = {1: validate_id(args.world_id), 2: validate_id(args.system_id),
           3: validate_id(args.notify_id)}
    if len(set(ids.values())) != 3:
        raise ValueError("conversation IDs must differ")
    if not APK.is_file() or base.sha256(APK) != APK_SHA256:
        raise ValueError("pinned current APK missing or changed")
    with zipfile.ZipFile(APK) as apk:
        before_bundle = apk.read(BUNDLE)
        before_fixture = apk.read(FIXTURES)
        before_index = apk.read(INDEX)
    patched_bundle = patch_bundle(before_bundle, origin)
    patched_fixture = patch_fixture(before_fixture, ids)
    patched_index = base.patch_index(before_index,
                                     {"/config/clientexel/clientplatformconstant.ab": patched_bundle})
    if patched_index == before_index:
        raise ValueError("bundle index did not change")
    print(json.dumps({
        "status": "asset_patch_feasible_only",
        "apk": str(APK),
        "origin": origin,
        "conversationIds": ids,
        "changes": {
            BUNDLE: {"oldBytes": len(before_bundle), "newBytes": len(patched_bundle),
                     "sha256": hashlib.sha256(patched_bundle).hexdigest()},
            FIXTURES: {"oldBytes": len(before_fixture), "newBytes": len(patched_fixture),
                       "sha256": hashlib.sha256(patched_fixture).hexdigest()},
            INDEX: {"oldBytes": len(before_index), "newBytes": len(patched_index),
                    "sha256": hashlib.sha256(patched_index).hexdigest()},
        },
        "apkCreated": False,
        "apkInstalled": False,
        "rtmHandshakeTested": False,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
