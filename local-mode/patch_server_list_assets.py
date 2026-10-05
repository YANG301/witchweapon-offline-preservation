"""Hide the old visitor entry and describe both zones in the original UI."""

from __future__ import annotations

import hashlib
import zipfile

import UnityPy


PREFAB = "assets/assetbundle/assets/resources/ui/prefab/login/loginmain.ab"
SCENE = "assets/assetbundle/scene/loginfromal.ab"
REVIEWED = {
    PREFAB: "16dcc8074ba6d54835ded564a885a242de3d97603d98b5149c4fa0bd48b1b8cd",
    SCENE: "9f716798645c05313d3c14f13360ac153715bc5954d090faab76203d66fe2112",
}
NOTICE = "新丰洲：线上怀旧服\n本地模式：电脑单人存档，需连接本地服务"


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _edit(raw: bytes, name: str, file_name: str | None,
          visitor_id: int, notice_id: int) -> bytes:
    if sha(raw) != REVIEWED[name]:
        raise ValueError("Unexpected login bundle: " + name)
    bundle = UnityPy.load(raw)
    if file_name is None:
        objects = {item.path_id: item for item in bundle.objects}
        expected_count = 4704
    else:
        objects = bundle.file.files[file_name].objects
        expected_count = 4649
    if len(objects) != expected_count:
        raise ValueError("Login object inventory changed")
    before = {key: sha(item.get_raw_data()) for key, item in objects.items()}
    visitor = objects[visitor_id]
    notice = objects[notice_id]
    vtree = visitor.read_typetree()
    ntree = notice.read_typetree()
    if (vtree.get("m_Name") != "RegistBtn" or vtree.get("m_IsActive") is not True
            or ntree.get("mText") != ""):
        raise ValueError("Reviewed visitor/notice objects changed")
    vtree["m_IsActive"] = False
    ntree["mText"] = NOTICE
    visitor.save_typetree(vtree)
    notice.save_typetree(ntree)
    output = bundle.file.save(packer="original")
    check = UnityPy.load(output)
    if file_name is None:
        after = {item.path_id: item for item in check.objects}
    else:
        after = check.file.files[file_name].objects
    if set(before) != set(after):
        raise ValueError("Patched login object inventory changed")
    changed = {key for key, item in after.items() if sha(item.get_raw_data()) != before[key]}
    if changed != {visitor_id, notice_id}:
        raise ValueError("Unrelated login object changed: " + str(changed))
    if (after[visitor_id].read_typetree()["m_IsActive"] is not False
            or after[notice_id].read_typetree()["mText"] != NOTICE):
        raise ValueError("Patched login UI failed round trip")
    return output


def patch(raw_assets: dict[str, bytes]) -> dict[str, bytes]:
    if set(raw_assets) != {PREFAB, SCENE}:
        raise ValueError("Both reviewed login bundles are required")
    return {
        PREFAB: _edit(raw_assets[PREFAB], PREFAB, None,
                      1014635688734296921, -5014475394988244260),
        SCENE: _edit(raw_assets[SCENE], SCENE, "BuildPlayer-LoginFromal",
                     413, 2897),
    }


if __name__ == "__main__":
    source = r"E:\Desktop\魔女兵器本地模式\魔女兵器-在线本地整合-v109-测试.apk"
    with zipfile.ZipFile(source) as apk:
        result = patch({name: apk.read(name) for name in REVIEWED})
    print({name: {"old": REVIEWED[name], "new": sha(value), "size": len(value)}
           for name, value in result.items()})
