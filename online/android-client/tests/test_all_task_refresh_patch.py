"""Static acceptance for the pinned original daily-task Lua patch.

No APK is built and no output bundle is written to disk.
"""

from __future__ import annotations

from pathlib import Path
import re
import sys
import unittest

import UnityPy


CLIENT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CLIENT))
import patch_all_task_refresh as patch  # noqa: E402


def assets(raw: bytes) -> dict[str, str]:
    return {tree["m_Name"]: tree["m_Script"]
            for obj in UnityPy.load(raw).objects if obj.type.name == "TextAsset"
            for tree in (obj.read_typetree(),)
            if tree.get("m_Name") in patch.EXPECTED_ASSETS}


class PinnedDailyTaskPatchTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        source = patch.read_pinned_apk()
        cls.original = source
        cls.patched, cls.changed = patch.patch_bundles(source)

    def test_only_required_lua_assets_change(self) -> None:
        self.assertEqual(self.changed[patch.UI_MEMBER],
                         ["ActivityView.lua", "UIActivitiesFormat60.lua"])
        self.assertEqual(self.changed[patch.PATCH_MEMBER], ["TaskItemPatch.lua"])

    def test_three_original_entries_request_native_quest_refresh(self) -> None:
        ui = assets(self.patched[patch.UI_MEMBER])
        for name in ("ActivityView.lua", "UIActivities.lua", "UIActivitiesFormat60.lua"):
            script = ui[name]
            self.assertEqual(script.count("WaterBell.ProjX.Data.NetIO.GetAllQuest"), 1, name)
            self.assertLess(script.index("WaterBell.ProjX.Data.NetIO.GetAllQuest"),
                            script.index("TASK_SCENE"), name)
        self.assertEqual(ui["UIActivities.lua"], assets(self.original[patch.UI_MEMBER])["UIActivities.lua"])

    def test_native_row_repaints_status_and_count(self) -> None:
        row = assets(self.patched[patch.PATCH_MEMBER])["TaskItemPatch.lua"]
        for marker in ("StatusChanged", "MetaChanged", "conditionCount", "CHECK_INTERVAL = 0.5"):
            self.assertIn(marker, row)
        self.assertIn("methodStatus:Call(row.view, status)", row)
        self.assertIn("methodMeta:Call(row.view, meta)", row)
        self.assertIn("tolua.getmethod(rowType, 'StatusChanged', intType)", row)
        self.assertIn("tolua.getmethod(rowType, 'MetaChanged', intType)", row)
        self.assertIn("intType = typeof('System.Int32')", row)
        self.assertNotIn("tolua.gettypemethod(rowType, 'StatusChanged', 65535)", row)
        self.assertLess(row.index("methodStatus:Call(row.view, status)"),
                        row.index("not hasCounter(typeID)"))

    def test_tolua_runtime_call_arity_matches_original_view(self) -> None:
        # These are the recovered C# sources for the APK's original ToLua
        # reflection bridge and QuestInfoView. In this bridge, getmethod
        # records explicit parameter types; Call then requires self + view +
        # exactly that many arguments for an instance method.
        scripts = Path(r"D:\Project\魔女兵器工程恢复\原版\Unity恢复\ExportedProject"
                       r"\Assets\Scripts\Assembly-CSharp")
        view = (scripts / "QuestInfoView.cs").read_text(encoding="utf-8-sig")
        reflection = (scripts / "LuaInterface" / "LuaReflection.cs").read_text(encoding="utf-8-sig")
        method = (scripts / "LuaInterface" / "LuaMethod.cs").read_text(encoding="utf-8-sig")
        row = assets(self.patched[patch.PATCH_MEMBER])["TaskItemPatch.lua"]
        for method_name, value_name in (("StatusChanged", "status"), ("MetaChanged", "meta")):
            self.assertRegex(view, rf"void {method_name}\(int value\)")
            self.assertIn(f"tolua.getmethod(rowType, '{method_name}', intType)", row)
            self.assertIn(f"method{method_name.removesuffix('Changed')}:Call(row.view, {value_name})", row)
        self.assertIn("types = new Type[count - 2]", reflection)
        self.assertIn("PushLuaMethod(L, md, t, types)", reflection)
        self.assertIn("list.AddRange(types)", method)
        self.assertIn("offset += 1;\n                obj = ToLua.CheckObject(L, 2, kclass);", method)
        self.assertIn("ToLua.CheckArgsCount(L, list.Count + offset)", method)

    def test_fail_closed_on_modified_bundles(self) -> None:
        wrong = dict(self.original)
        wrong[patch.UI_MEMBER] += b"changed"
        with self.assertRaisesRegex(ValueError, "Unreviewed Lua bundle"):
            patch.patch_bundles(wrong)


if __name__ == "__main__":
    unittest.main()
