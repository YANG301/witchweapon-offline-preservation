"""Append one post-battle progress refresh listener to the reviewed v16 Lua bundle."""

from __future__ import annotations

import hashlib
from pathlib import Path

import UnityPy


HERE = Path(__file__).resolve().parent
BLOBS = HERE.parent / "热更新测试" / "主线热更候选" / "blobs"
BASE_SHA256 = "d663ea321d32649ec735b84f4ff88e6d099095100e99c98734d43bd3733a54c5"
BASE_OBJECT_SHA256 = "b2d204bf21722a518625e501c69231bb153fcc46dc84324cba6f5cb0239c793d"
BASE_SCRIPT_SHA256 = "844d670eb4ec0e8579464eedfd7b280a6f0b1971ce0d67c7dec67a93d3258429"
SOURCE = HERE / "lua" / "init-dungeon-sweep-refresh.lua"


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def patch() -> tuple[str, int]:
    raw = (BLOBS / BASE_SHA256).read_bytes()
    if digest(raw) != BASE_SHA256:
        raise ValueError("Reviewed v16 startup bundle changed")
    block = SOURCE.read_text(encoding="utf-8")
    if ("ONLINE_DUNGEON_PROGRESS_REFRESH" not in block
            or "ONLINE_DUNGEON_COUNT_REPAIRED" not in block
            or "GetProgressByChapterID" not in block
            or "BattleCount" not in block
            or "UserAllProgressLogic" not in block
            or "SettlementUI" not in block):
        raise ValueError("Dungeon refresh listener is incomplete")
    bundle = UnityPy.load(raw)
    before = {obj.path_id: digest(obj.get_raw_data()) for obj in bundle.objects}
    found = [obj for obj in bundle.objects if obj.type.name == "TextAsset"
             and obj.read_typetree().get("m_Name") == "init.lua"]
    if len(found) != 1 or before[found[0].path_id] != BASE_OBJECT_SHA256:
        raise ValueError("Reviewed init.lua object is missing")
    target = found[0]
    tree = target.read_typetree()
    old = tree.get("m_Script")
    if (not isinstance(old, str) or digest(old.encode("utf-8")) != BASE_SCRIPT_SHA256
            or "ONLINE_DUNGEON_PROGRESS_REFRESH" in old):
        raise ValueError("Reviewed init.lua script changed")
    expected = old + "\n" + block
    tree["m_Script"] = expected
    target.save_typetree(tree)
    output = bundle.file.save(packer="original")
    check = UnityPy.load(output)
    after = {obj.path_id: digest(obj.get_raw_data()) for obj in check.objects}
    if set(before) != set(after) or {key for key in before if before[key] != after[key]} != {target.path_id}:
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
    print("DUNGEON_SWEEP_REFRESH_BUNDLE_OK", sha, size)
