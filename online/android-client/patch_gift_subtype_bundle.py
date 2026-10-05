"""Restore the seven public gift boxes to original subtype 5 (contents view)."""

from __future__ import annotations

import codecs
import hashlib
from pathlib import Path
import zipfile

from patch_feature_level_gates import _csv_tree


HERE = Path(__file__).resolve().parent
SOURCE_APK = HERE / "build" / "witchweapon-dungeon-count-v96-test.apk"
SOURCE_SHA256 = "8611eff64d9698c9bc41066ef2130c2b216caf6ebf5d95a6c8686dd472db1dc3"
MEMBER = "assets/assetbundle/config/clientexel/item.ab"
SOURCE_BUNDLE_SHA256 = "67736f3556d59cf5d72abed2fac89a6ff75db2ef5b2c7fbc3223d9fa64d4dcab"
ORIGINAL = Path(r"D:\Project\魔女兵器工程恢复\原版\可读脚本与配置"
                r"\配置\clientexel\item.txt")
ORIGINAL_SHA256 = "74df3a598acb1e0d52ef95439bb3486406dcbce40334848f27ec14c4f4c8e3ce"
BLOBS = HERE.parent / "热更新测试" / "主线热更候选" / "blobs"
GIFT_ITEMS = frozenset({
    "40950044", "40950052", "40940027", "40950058",
    "40950060", "40940028", "40940029",
})


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def reference_rows(text: str, index: int) -> dict[str, list[str]]:
    found = {}
    for line in text.splitlines()[3:]:
        fields = line.split(",")
        if fields[0] in GIFT_ITEMS:
            if fields[0] in found or fields[index] != "5":
                raise ValueError("Original gift subtype is unexpected")
            found[fields[0]] = fields
    if set(found) != GIFT_ITEMS:
        raise ValueError("Original gift items are incomplete")
    return found


def patch_text(current: str, original: str) -> str:
    header = current.splitlines()[0].split(",")
    if header != original.splitlines()[0].split(","):
        raise ValueError("Item CSV schema differs from original")
    index = header.index("item_sub_type")
    reference = reference_rows(original, index)
    found = set()
    result = []
    for line in current.splitlines(keepends=True):
        payload = line.rstrip("\r\n")
        ending = line[len(payload):]
        fields = payload.split(",")
        item_id = fields[0]
        if item_id in GIFT_ITEMS:
            if item_id in found or fields[index] != "14":
                raise ValueError("Current gift subtype is unexpected")
            found.add(item_id)
            if (len(fields) != len(reference[item_id])
                    or any(a != b for pos, (a, b) in enumerate(zip(fields, reference[item_id]))
                           if pos != index)):
                raise ValueError("Gift reward data differs from original")
            fields[index] = "5"
            line = ",".join(fields) + ending
            if fields != reference[item_id]:
                raise ValueError("Gift row failed original comparison")
        result.append(line)
    if found != GIFT_ITEMS:
        raise ValueError("Current gift items are incomplete")
    return "".join(result)


def patch() -> tuple[str, int]:
    with SOURCE_APK.open("rb") as source:
        if hashlib.file_digest(source, "sha256").hexdigest() != SOURCE_SHA256:
            raise ValueError("Reviewed v96 APK changed")
    original_raw = ORIGINAL.read_bytes()
    if digest(original_raw) != ORIGINAL_SHA256:
        raise ValueError("Original Item table changed")
    with zipfile.ZipFile(SOURCE_APK) as apk:
        raw = apk.read(MEMBER)
    if digest(raw) != SOURCE_BUNDLE_SHA256:
        raise ValueError("Reviewed Item bundle changed")
    env, obj, tree, current, has_bom = _csv_tree(raw, "Item")
    updated = patch_text(current, original_raw.decode("utf-8-sig"))
    encoded = (codecs.BOM_UTF8 if has_bom else b"") + updated.encode("utf-8")
    tree["bytes"] = [byte ^ 255 for byte in encoded]
    obj.save_typetree(tree)
    output = env.file.save(packer="original")
    check, _, _, actual, bom_after = _csv_tree(output, "Item")
    if actual != updated or bom_after != has_bom:
        raise ValueError("Gift Item bundle failed round-trip")
    before = {o.path_id: digest(o.get_raw_data()) for o in _csv_tree(raw, "Item")[0].objects}
    after = {o.path_id: digest(o.get_raw_data()) for o in check.objects}
    if (set(before) != set(after)
            or {key for key in before if before[key] != after[key]} != {obj.path_id}):
        raise ValueError("Unrelated Item bundle object changed")
    sha = digest(output)
    target = BLOBS / sha
    if target.exists():
        if digest(target.read_bytes()) != sha:
            raise ValueError("Content-addressed Item blob is occupied")
    else:
        target.write_bytes(output)
    return sha, len(output)


if __name__ == "__main__":
    sha, size = patch()
    print("ORIGINAL_GIFT_CONTENTS_BUNDLE_OK", sha, size)
