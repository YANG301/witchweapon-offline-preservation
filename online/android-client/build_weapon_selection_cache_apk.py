"""Compose a separate weapon-cache candidate from an existing test APK.

Prepare changes only lua.ab/init.lua and its original resource-index entry.
--build signs an isolated candidate with the existing test signing identity.
This never installs an APK, publishes hot updates or changes a running service.
The input can be the later settlement candidate; all of its fixes are retained.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import zipfile

sys.dont_write_bytecode = True

import patch_weapon_selection_cache as patch


INDEX = "assets/m.assets_list.txt"
NATIVE = "lib/arm64-v8a/libil2cpp.so"
VERIFIED_METHODS = {
    "BasicPlayMode.SelectCards": (
        0x3D38C84, 532,
        "f23e484ebc80212d8f832f63a962b5f1c7c37c16852af6a78e087c77bbb4fe59"),
    "BasicPlayMode.SwitchWeapon": (
        0x3D39E40, 948,
        "7e04481ab2f16d2fd2e3e54b0435838bb44bf8b651a75af05d7f62896b5ef31d"),
    "BasicPlayMode.SelectWeaponByCache": (
        0x3D38E98, 4008,
        "94f45adde8a0f988bd64bff97367366706a259cf3230865aaab5f1038c7d906f"),
    "BasicPlayMode.CacheSave": (
        0x3D35580, 752,
        "7851163fad4380c2ff87d82bb2b31666d9dd85667553f72a4a46f490289c68d6"),
    "EventDelegate.Equals": (
        0x1691FC8, 568,
        "8258599edb7cf67b114eae983e037dd76f8afc830c8f74b41eeaa790375cdb2d"),
    "EventDelegate.Set.Callback": (
        0x16911CC, 368,
        "5816ec38b39c532cf408a707ee31d6b30a10ed566a54d7ab067dfbb2f5f88278"),
    "EventDelegate.Add.Callback.bool": (
        0x1693688, 376,
        "74a0f2e7b77b5f3cba8c146e2bc8ed0d8bd8180792ba2d65af250651eb2dd674"),
    "EventDelegate.Execute.List": (
        0x16931B0, 628,
        "8105e05ca53607999b7a4f2c99caddea3638667f043b9bcbd0b78bd86429a87b"),
    "System.Object.ReferenceEquals": (
        0x25E0578, 12,
        "153e93632b4e8c817d8ce3166b714b56e3da31697fce6589a8cac8c268b53d96"),
}


def file_sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def native_file_offset(raw: bytes, address: int) -> int:
    import struct
    if raw[:6] != b"\x7fELF\x02\x01":
        raise ValueError("Reviewed client requires little-endian ELF64")
    if struct.unpack_from("<H", raw, 18)[0] != 183:
        raise ValueError("Reviewed client requires AArch64")
    phoff = struct.unpack_from("<Q", raw, 32)[0]
    phsize, phcount = struct.unpack_from("<HH", raw, 54)
    matches = []
    for index in range(phcount):
        ptype, flags, offset, virtual, _, filesz, _, _ = struct.unpack_from(
            "<IIQQQQQQ", raw, phoff + index * phsize)
        if ptype == 1 and flags & 1 and virtual <= address < virtual + filesz:
            matches.append(offset + address - virtual)
    if len(matches) != 1:
        raise ValueError("Native address is not in one executable load segment")
    return matches[0]


def prepare(source: Path, client_root: Path) -> tuple[dict[str, bytes], dict]:
    sys.path.insert(0, str(client_root))
    from build_online_apk import patch_index

    input_hash = file_sha(source)
    with zipfile.ZipFile(source) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise ValueError("Input APK contains duplicate members")
        native = archive.read(NATIVE)
        for name, (address, length, expected) in VERIFIED_METHODS.items():
            offset = native_file_offset(native, address)
            if patch.sha(native[offset:offset + length]) != expected:
                raise ValueError("Unreviewed native weapon-selection method: " + name)
        before = archive.read(patch.MEMBER)
        after = patch.patch_bundle(before)
        index = patch_index(archive.read(INDEX), {patch.LOGICAL_PATH: after})
        changes = {patch.MEMBER: after, INDEX: index}
        metadata = {
            "status": "prepared_static_validation_only",
            "source": str(source.resolve()),
            "sourceSha256": input_hash,
            "sourceLuaSha256": patch.sha(before),
            "patchedLuaSha256": patch.sha(after),
            "changedPayloadMembers": sorted(changes),
            "nativeMethodsVerified": list(VERIFIED_METHODS),
            "existingInitPrefixPreserved": True,
            "unrelatedUnityObjectsPreserved": True,
            "deviceValidated": False,
            "installed": False,
            "deployed": False,
        }
    if file_sha(source) != input_hash:
        raise ValueError("Input APK changed while preparing the observer")
    return changes, metadata


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True,
                        help="Existing v110 or later compatible test APK")
    parser.add_argument("--client-root", type=Path,
                        default=Path(r"D:\Project\魔女兵器在线版\android-client"))
    parser.add_argument("--output", type=Path, required=True,
                        help="New isolated output directory; never overwritten")
    parser.add_argument("--build", action="store_true")
    parser.add_argument("--temp", type=Path,
                        default=Path(r"D:\Environment\Android\temp\wwr-weapon-selection-cache"))
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("Refusing to overwrite candidate output")
    if args.build and args.temp.exists():
        raise FileExistsError("Refusing to reuse an existing signing directory")
    changes, metadata = prepare(args.source, args.client_root)
    args.output.mkdir(parents=True)
    (args.output / "weapon-selection-cache-lua.ab").write_bytes(changes[patch.MEMBER])
    (args.output / "m.assets_list.txt").write_bytes(changes[INDEX])
    report = args.output / "weapon-selection-cache-validation.json"
    if args.build:
        import build_original_ui_quest_refresh_v6_apk as signer
        from build_original_ui_lottery_lua_input_probe_apk import cert_digest

        signer.SOURCE = args.source.resolve()
        signer.SOURCE_SHA256 = metadata["sourceSha256"]
        signer.TEMP = args.temp.resolve()
        result = args.output / "witchweapon-weapon-selection-cache-test.apk"
        # Its reusable signer returns neutral validation values alongside old
        # quest-specific labels. Replace that transient report with this task's
        # metadata below, so no unrelated claims survive in the deliverable.
        signed = signer.build(changes, result, report)
        command = [signer.JAVA, "-jar", signer.TOOLS / "lib/apksigner.jar",
                   "verify", "--print-certs"]
        original_cert = cert_digest(signer.run([*command, args.source], signer.signer_env()))
        new_cert = cert_digest(signer.run([*command, result], signer.signer_env()))
        if original_cert != new_cert:
            raise ValueError("Test APK signing identity differs from input APK")
        metadata.update({
            "status": "signed_static_validation_only",
            "testApk": signed["testApk"],
            "signatureVerification": signed["signatureVerification"],
            "alignmentVerification": signed["alignmentVerification"],
            "sameSigningIdentity": True,
            "unchangedPayloadMembersCheckedByZipMetadata":
                signed["unchangedPayloadMembersCheckedByZipMetadata"],
        })
    report.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(metadata, ensure_ascii=False))


if __name__ == "__main__":
    main()
