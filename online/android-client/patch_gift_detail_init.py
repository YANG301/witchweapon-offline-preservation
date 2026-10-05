"""Update only the original shop presentation block in the reviewed v18 Lua bundle."""

from __future__ import annotations

import hashlib
from pathlib import Path

import UnityPy


HERE = Path(__file__).resolve().parent
BLOBS = HERE.parent / "热更新测试" / "主线热更候选" / "blobs"
BASE_SHA256 = "7eedd74aa0e7306864a44fbe405f087d8c2cc709e9aa8ea13014c1656ae38a05"
BASE_OBJECT_SHA256 = "3ec93b9fe2808c658d0f0343df12e4dc9b723b7d554f4ff410d00baee5b7c47c"
BASE_SCRIPT_SHA256 = "b27908b1b606f5bf59e7ecb8fdf66c348b3307d0e1e11897f8a070f3b8841823"
START = "-- Local test client only. This block is appended"
END = "-- Guild UI is created after MainScenePanel is hidden."
SOURCE = HERE / "lua" / "init-shop-presentation-local.lua"


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def patch() -> tuple[str, int]:
    raw = (BLOBS / BASE_SHA256).read_bytes()
    if digest(raw) != BASE_SHA256:
        raise ValueError("Reviewed v18 Lua bundle changed")
    bundle = UnityPy.load(raw)
    before = {obj.path_id: digest(obj.get_raw_data()) for obj in bundle.objects}
    found = [obj for obj in bundle.objects if obj.type.name == "TextAsset"
             and obj.read_typetree().get("m_Name") == "init.lua"]
    if len(found) != 1 or before[found[0].path_id] != BASE_OBJECT_SHA256:
        raise ValueError("Reviewed init.lua object is missing")
    target = found[0]
    tree = target.read_typetree()
    old = tree.get("m_Script")
    if not isinstance(old, str) or digest(old.encode("utf-8")) != BASE_SCRIPT_SHA256:
        raise ValueError("Reviewed init.lua script changed")
    if old.count(START) != 1 or old.count(END) != 1:
        raise ValueError("Cannot isolate original shop presentation block")
    start, end = old.index(START), old.index(END)
    previous = old[start:end]
    if not previous.endswith("end\n\n") or "LOCAL_SHOP_PRESENTATION" not in previous:
        raise ValueError("Shop presentation block boundaries changed")
    replacement = SOURCE.read_text(encoding="utf-8")
    if (not replacement.startswith(START)
            or "refreshGiftDescription(shop, setID)" not in replacement
            or "['45030621']" not in replacement
            or "LOCAL_SHOP_PRESENTATION" not in replacement):
        raise ValueError("Gift description source is incomplete")
    expected = old[:start] + replacement.rstrip("\n") + "\n\n" + old[end:]
    if expected[:start] != old[:start] or expected[expected.index(END):] != old[end:]:
        raise ValueError("Unrelated startup script changed")
    tree["m_Script"] = expected
    target.save_typetree(tree)
    output = bundle.file.save(packer="original")
    check = UnityPy.load(output)
    after = {obj.path_id: digest(obj.get_raw_data()) for obj in check.objects}
    if (set(before) != set(after)
            or {key for key in before if before[key] != after[key]} != {target.path_id}):
        raise ValueError("Unrelated Unity objects changed")
    matching = [obj for obj in check.objects if obj.path_id == target.path_id]
    if len(matching) != 1 or matching[0].read_typetree().get("m_Script") != expected:
        raise ValueError("Patched Lua failed round-trip")
    sha = digest(output)
    path = BLOBS / sha
    if path.exists():
        if digest(path.read_bytes()) != sha:
            raise ValueError("Content-addressed blob is occupied")
    else:
        path.write_bytes(output)
    return sha, len(output)


if __name__ == "__main__":
    sha, size = patch()
    print("GIFT_DETAIL_BUNDLE_OK", sha, size)
