"""Sign isolated v5 candidates with corrected original password UI copy.

Both outputs inherit their own reviewed v4 code and endpoint unchanged. Only
the dictionary, login scene, and their bundle-index entries are replaced.
Nothing is installed or deployed by this builder.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import zipfile

import build_original_ui_quest_refresh_v6_apk as signer
from build_original_ui_lottery_lua_input_probe_apk import cert_digest
from build_online_apk import patch_index
import patch_password_copy_v5 as copy_patch


HERE = Path(__file__).resolve().parent
BUILD = HERE / "build"
TEMP_PARENT = Path(r"D:\Environment\Android\temp")
INDEX = "assets/m.assets_list.txt"
EXPECTED_INDEX_SHA256 = "dcb2395d24d2afc9385f039635aef7d723e0665e996c084cf3ded431daa1db28"
SOURCE = {
    "candidate": (
        BUILD / "witchweapon-online-bugfix-v4-test.apk",
        "ba4ab0878301dbf06075714008ea57fa0aac9665846179cc129f9eab9164d748",
        BUILD / "witchweapon-online-password-copy-v5-test.apk",
        BUILD / "密码提示修复候选包验收-v5.json",
        b"https://212.192.15.11:18443\n",
    ),
    "staging": (
        BUILD / "witchweapon-online-local-staging-v4.apk",
        "411a743a20a747cedafc8ef66198ecb4daa4187d60405ca216276ab89d9a07a6",
        BUILD / "witchweapon-online-local-staging-password-copy-v5.apk",
        BUILD / "本地测试服密码提示修复验收-v5.json",
        b"https://127.0.0.1:19443\n",
    ),
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def prepare(kind: str) -> tuple[dict[str, bytes], dict[str, str]]:
    source, source_sha, _, _, endpoint = SOURCE[kind]
    if sha256_file(source) != source_sha:
        raise ValueError("Reviewed v4 source APK differs: " + kind)
    with zipfile.ZipFile(source) as apk:
        if len(apk.namelist()) != len(set(apk.namelist())):
            raise ValueError("Duplicate source APK members")
        if apk.read("assets/online_endpoint.txt") != endpoint:
            raise ValueError("Unexpected source endpoint: " + kind)
        old_index = apk.read(INDEX)
        if copy_patch.sha256(old_index) != EXPECTED_INDEX_SHA256:
            raise ValueError("Unreviewed bundle index")
        raw = {name: apk.read(name) for name in copy_patch.INDEX_NAMES}
    patched = copy_patch.patch_bundles(raw)
    new_index = patch_index(old_index, {
        copy_patch.INDEX_NAMES[name]: updated for name, updated in patched.items()
    })
    changed = dict(patched)
    changed[INDEX] = new_index
    return changed, {
        "sourceApkSha256": source_sha,
        "sourceEndpoint": endpoint.decode("ascii").strip(),
        "dictionaryBundleSha256": copy_patch.sha256(patched[copy_patch.DICTIONARY_MEMBER]),
        "loginSceneBundleSha256": copy_patch.sha256(patched[copy_patch.LOGIN_MEMBER]),
        "bundleIndexSha256": copy_patch.sha256(new_index),
    }


def build_one(kind: str, changes: dict[str, bytes], detail: dict[str, str]) -> dict:
    source, source_sha, result, report_path, endpoint = SOURCE[kind]
    temp = TEMP_PARENT / ("witch-online-password-copy-v5-" + kind)
    if temp.exists():
        raise ValueError("Stale password-copy build temp: " + str(temp))
    try:
        signer.SOURCE = source
        signer.SOURCE_SHA256 = source_sha
        signer.TEMP = temp
        report = signer.build(changes, result, report_path)
        check = [signer.JAVA, "-jar", signer.TOOLS / "lib/apksigner.jar",
                 "verify", "--print-certs"]
        before = cert_digest(signer.run([*check, source], signer.signer_env()))
        after = cert_digest(signer.run([*check, result], signer.signer_env()))
        if before != after:
            raise ValueError("APK signer certificate changed")
        with zipfile.ZipFile(source) as old, zipfile.ZipFile(result) as new:
            for member in ("AndroidManifest.xml", "classes.dex", "classes2.dex",
                           "assets/online_endpoint.txt"):
                if old.read(member) != new.read(member):
                    raise ValueError("Unrelated client component changed: " + member)
            if new.read("assets/online_endpoint.txt") != endpoint:
                raise ValueError("Signed APK endpoint changed")
        report.update(detail)
        report["signerCertificateSha256"] = after
        report["loginUiPasswordLength"] = "12-16 characters (original input limit: 16)"
        report["authApiPasswordLength"] = "12-128 characters (unchanged)"
        report["changedUnityObjects"] = {
            "DictionaryStatic": ["CE10114", "password placeholder translation"],
            "LoginFromal": sorted(copy_patch.SCENE_IDS),
        }
        report["runtimeValidated"] = False
        for stale in ("changedUnityTextAsset", "originalUnityTextAssetSha256",
                      "preservesV4TaskItemPatch", "nativeRefreshClass"):
            report.pop(stale, None)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                               encoding="utf-8")
        # The APK v4 incremental-install sidecar is unnecessary for normal ADB
        # install and should not take disk space beside this candidate.
        sidecar = Path(str(result) + ".idsig")
        if sidecar.is_file():
            sidecar.unlink()
        if sha256_file(result) != report["testApk"]["sha256"]:
            raise ValueError("Final signed APK differs from verification record")
        return report
    finally:
        if temp.exists():
            resolved = temp.resolve()
            if resolved.parent != TEMP_PARENT.resolve() or \
                    resolved.name != "witch-online-password-copy-v5-" + kind:
                raise ValueError("Unsafe password-copy temp cleanup target")
            shutil.rmtree(resolved)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", action="store_true", help="Sign both v5 APKs")
    args = parser.parse_args()
    candidates = {kind: prepare(kind) for kind in SOURCE}
    candidate_changes, _ = candidates["candidate"]
    staging_changes, _ = candidates["staging"]
    for member in (*copy_patch.INDEX_NAMES, INDEX):
        if candidate_changes[member] != staging_changes[member]:
            raise ValueError("Production/test UI copies diverged: " + member)
    if args.build:
        for kind in SOURCE:
            report = build_one(kind, *candidates[kind])
            print(kind.upper() + "_PASSWORD_COPY_V5_READY", report["testApk"]["sha256"])
    else:
        print("PASSWORD_COPY_V5_STATIC_OK", json.dumps({
            "changedMembers": sorted(candidate_changes),
            "dictionarySha256": copy_patch.sha256(candidate_changes[copy_patch.DICTIONARY_MEMBER]),
            "sceneSha256": copy_patch.sha256(candidate_changes[copy_patch.LOGIN_MEMBER]),
        }))


if __name__ == "__main__":
    main()
