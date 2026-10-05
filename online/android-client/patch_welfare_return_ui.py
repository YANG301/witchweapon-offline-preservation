"""Repair the original welfare-return Lua UI in the v99 AssetBundle."""

from __future__ import annotations

import hashlib
from pathlib import Path
import zipfile

import UnityPy


HERE = Path(__file__).resolve().parent
APK = HERE / "build/witchweapon-monthly-mail-v99-test.apk"
MEMBER = "assets/assetbundle/lua/lua_projx_ui.ab"
BLOBS = HERE.parent / "热更新测试/主线热更候选/blobs"
BASE_BUNDLE = "d085dce599861feb5c03723f706b655fffc8a8b85e0982874d27967aa451c770"
BASE_SCRIPTS = {
    "UIActivitiesFormat61.lua": "0f5326c3349d51a6ffaf5eb4ace8fad6c4f926c91eeb1c8d541083619ba709a1",
    "UIActivitiesButtons.lua": "bd0c93749a705ee05b4dc1f685ab08f79a5ed51bda1d34dd8c11b36007fc584e",
}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def replace_one(source: str, old: str, new: str) -> str:
    if source.count(old) != 1:
        raise ValueError("Expected exactly one welfare UI anchor: " + old[:70])
    return source.replace(old, new, 1)


def format61(source: str) -> str:
    return replace_one(source,
        "\t--this.hide2show( data )\n\tUIActivitiesModel.RequestActivitiesData( UIActivitiesButtons.updateInfo )",
        "\t-- Render the cached original activity immediately. UIActivitiesButtons\n"
        "\t-- requests current server progress after the panel is visible.\n"
        "\tthis.hide2show(data)")


def buttons(source: str) -> str:
    source = replace_one(source, "local format\n", "local format\nlocal welfareRefreshInFlight = false\n")
    source = replace_one(source, "\ttPages = {}\nend\n\nfunction this.clearOnReload",
                         "\ttPages = {}\n\twelfareRefreshInFlight = false\nend\n\nfunction this.clearOnReload")
    source = replace_one(source, "local function openOne( id,panel_id )",
                         "local function openOne( id,panel_id,skipWelfareRefresh )")
    source = replace_one(source, "if not table.containValue(t) then",
                         "if not table.containValue(tPages,t) then")
    source = replace_one(source,
        "\tLuaPanelHelper.SetLuaPanelCache('UIActivitiesButtons',index .. '|' .. format)\nend",
        "\tLuaPanelHelper.SetLuaPanelCache('UIActivitiesButtons',index .. '|' .. format)\n"
        "\t-- A free gift or recharge updates the server ledger immediately. Refresh\n"
        "\t-- only when the player opens welfare return; do not loop on repaint.\n"
        "\tif id == 11 and panel_id == 61 and not skipWelfareRefresh and not welfareRefreshInFlight then\n"
        "\t\twelfareRefreshInFlight = true\n"
        "\t\tUIActivitiesModel.RequestActivitiesData(function()\n"
        "\t\t\twelfareRefreshInFlight = false\n"
        "\t\t\tif this.page and index == 11 and format == 61 then\n"
        "\t\t\t\tthis.updateInfo()\n"
        "\t\t\tend\n"
        "\t\tend)\n"
        "\tend\n"
        "end")
    source = replace_one(source,
        "\tloadButtonItems(true)\n\topenOne(index,format)\nend",
        "\tloadButtonItems(true)\n\topenOne(index,format,true)\nend")
    return source


def patch(raw: bytes) -> bytes:
    if sha(raw) != BASE_BUNDLE:
        raise ValueError("Reviewed v99 activity Lua bundle changed")
    bundle = UnityPy.load(raw)
    before = {obj.path_id: sha(obj.get_raw_data()) for obj in bundle.objects}
    targets = {}
    for obj in bundle.objects:
        if obj.type.name == "TextAsset":
            name = obj.read_typetree().get("m_Name")
            if name in BASE_SCRIPTS:
                if name in targets:
                    raise ValueError("Duplicate activity script: " + name)
                targets[name] = obj
    if set(targets) != set(BASE_SCRIPTS):
        raise ValueError("Original activity UI scripts missing")
    expected = {}
    for name, transform in (("UIActivitiesFormat61.lua", format61),
                            ("UIActivitiesButtons.lua", buttons)):
        obj = targets[name]
        tree = obj.read_typetree()
        original = tree.get("m_Script")
        if not isinstance(original, str) or sha(original.encode()) != BASE_SCRIPTS[name]:
            raise ValueError("Reviewed activity script changed: " + name)
        edited = transform(original)
        tree["m_Script"] = edited
        obj.save_typetree(tree)
        expected[obj.path_id] = edited
    output = bundle.file.save(packer="original")
    reopened = UnityPy.load(output)
    after = {obj.path_id: sha(obj.get_raw_data()) for obj in reopened.objects}
    if set(before) != set(after) or {pid for pid in before if before[pid] != after[pid]} != set(expected):
        raise ValueError("Welfare UI patch changed unrelated Unity objects")
    for obj in reopened.objects:
        if obj.path_id in expected and obj.read_typetree().get("m_Script") != expected[obj.path_id]:
            raise ValueError("Activity Lua round-trip failed")
    return output


def main() -> None:
    with zipfile.ZipFile(APK) as apk:
        result = patch(apk.read(MEMBER))
    digest = sha(result)
    target = BLOBS / digest
    if target.exists():
        if sha(target.read_bytes()) != digest:
            raise ValueError("Content-addressed blob differs")
    else:
        target.write_bytes(result)
    print("WELFARE_UI_BUNDLE_OK", digest, len(result))


if __name__ == "__main__":
    main()
