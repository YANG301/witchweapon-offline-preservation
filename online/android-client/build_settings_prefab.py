"""Patch the reviewed original settings prefab without publishing a release.

Reuse the hidden phone page's original tarot reward label/sprite in the email
header, and remove the empty password row from its expanded layout. Runtime Lua
uses the original controls and animations with authenticated email endpoints.
The registered email is read-only; no account data or rewards are changed here.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path

import UnityPy


ASSET_PATH = (
    "assetbundle/assets/resources/ui/prefab/usersetting/usersettingpanel.ab"
)
SOURCE_BUNDLE = Path(
    r"D:\Project\魔女兵器工程恢复\原版\Android工程\assets\assetbundle"
    r"\assets\resources\ui\prefab\usersetting\usersettingpanel.ab"
)
SOURCE_SHA256 = "5573edebb026f60f1394f1c6b85ba3574cf36fb54610d0b7c7efecffbf7bc75b"
SOURCE_SIZE = 127609
SOURCE_OBJECT_COUNT = 1931
CONTROLLER_ID = -5107853873690690358
COMPONENT_SCRIPT_ID = -4068213699369187015
LABEL_SCRIPT_ID = 6206998378989567730
EMAIL_COMPONENT_ID = -5601903355646174515
EMAIL_GO_ID = 6034767788836166048
EMAIL_TEXT_ID = 8145455437796671545
EMAIL_INPUT_ID = -2872689975448046893
EMAIL_INPUT_LABEL_ID = 8198225764873781495
EMAIL_CODE_INPUT_ID = 362338061754090127
EMAIL_PASSWORD_GO_ID = 2589266793177291569
EMAIL_TRANSFORM_ID = -7918921626422891675
EMAIL_TEXT_TRANSFORM_ID = -6864790776214162118
EMAIL_CODE_TRANSFORM_ID = -9040905108549376648
EMAIL_INPUT_TRANSFORM_ID = 7407026796150594054
EMAIL_CODE_SPRITE_ID = 4586305564101233651
EMAIL_BIND_WIDGET_ID = -2256544803880490177
EMAIL_CONTAINER_WIDGET_ID = -315770091385686786
PHONE_CONTAINER_TRANSFORM_ID = -2209104346411422371
REWARD_GO_ID = 2062461960009238155
REWARD_TRANSFORM_ID = 5661884475134753681
REWARD_LABEL_ID = -4426313702188435353
REWARD_SPRITE_ID = -2550280532691650317
REWARD_SPRITE_TRANSFORM_ID = -1685489834773403647
TELEPHONE_GO_ID = 4192917258165806707
IDCARD_GO_ID = -6094098591583355036
SERVICE_TEXT = "账号如遇到问题，请到测试群反馈。\n玩家QQ群：1078249413"
WEBSITE_TEXT = "www.witchweapon.wiki"
FREE_TEXT = "本游戏完全免费，没有任何付费内容"
EMAIL_TEXT = "验证奖励"
# Original Item 40350003 -> ItemClient 41350003 -> Item40_200 / Item40_200s.
# The existing phone reward sprite already uses the same currency icon/atlas.
REWARD_ICON_NAME = "Item40_200s"

# Exact fields allowed to differ. Inputs keep their original width and anchors.
# AnimForward resets both input transforms to its native three-row positions.
# Anchor the code widget to the email widget so NGUI restores the compact row
# after that reset. Code top = email bottom -10; its height stays 50.
PATCH_FIELDS = {
    -3075401596218027069: {"mText": SERVICE_TEXT},
    -1765947912211607504: {"mText": WEBSITE_TEXT, "mFontSize": 16},
    4251692791884884092: {"mText": FREE_TEXT},
    EMAIL_TEXT_ID: {
        "mText": EMAIL_TEXT,
        "mFontSize": 20,
        "mWidth": 90,
        "mHeight": 26,
        "mPivot": 3,
        "mAlignment": 1,
        "mColor": {"r": 0.30588236451148987, "g": 0.1882352977991104,
                   "b": 0.08627451211214066, "a": 1.0},
        "mMaxLineCount": 1,
    },
    EMAIL_TEXT_TRANSFORM_ID: {"m_LocalPosition": {"x": 190.0, "y": -25.0, "z": 0.0}},
    EMAIL_CODE_TRANSFORM_ID: {
        "m_LocalPosition": {"x": 29.0000057220459, "y": -80.0, "z": 0.0}},
    EMAIL_CODE_SPRITE_ID: {
        "leftAnchor": {"target": {"m_FileID": 0, "m_PathID": EMAIL_INPUT_TRANSFORM_ID},
                       "relative": 0.0, "absolute": 0},
        "rightAnchor": {"target": {"m_FileID": 0, "m_PathID": EMAIL_INPUT_TRANSFORM_ID},
                        "relative": 0.0, "absolute": 156},
        "bottomAnchor": {"target": {"m_FileID": 0, "m_PathID": EMAIL_INPUT_TRANSFORM_ID},
                         "relative": 0.0, "absolute": -60},
        "topAnchor": {"target": {"m_FileID": 0, "m_PathID": EMAIL_INPUT_TRANSFORM_ID},
                      "relative": 0.0, "absolute": -10},
        "updateAnchors": 1,
    },
    # Keep the original horizontal anchors/width. Derive the second row directly
    # from email even when verification hides the code input GameObject.
    EMAIL_BIND_WIDGET_ID: {
        "bottomAnchor": {"target": {"m_FileID": 0, "m_PathID": EMAIL_INPUT_TRANSFORM_ID},
                         "relative": 0.0, "absolute": -61},
        "topAnchor": {"target": {"m_FileID": 0, "m_PathID": EMAIL_INPUT_TRANSFORM_ID},
                      "relative": 0.0, "absolute": -9},
    },
    EMAIL_CONTAINER_WIDGET_ID: {"mHeight": 125},
    REWARD_GO_ID: {"m_Name": "EmailReward"},
    REWARD_TRANSFORM_ID: {
        "m_Father": {"m_FileID": 0, "m_PathID": EMAIL_TRANSFORM_ID},
        "m_LocalPosition": {"x": 333.0, "y": -25.0, "z": 0.0}},
    REWARD_LABEL_ID: {"mText": "×100", "mFontSize": 22, "mWidth": 84,
                      "mPivot": 3, "mMaxLineCount": 1},
    REWARD_SPRITE_TRANSFORM_ID: {
        "m_LocalPosition": {"x": -30.0, "y": 0.0, "z": 0.0}},
    # Parent children lists are reviewed and generated from their original order.
    EMAIL_TRANSFORM_ID: {},
    PHONE_CONTAINER_TRANSFORM_ID: {},
    EMAIL_INPUT_ID: {"m_Enabled": 0},
    EMAIL_INPUT_LABEL_ID: {"mText": "注册邮箱读取中"},
    EMAIL_CODE_INPUT_ID: {"characterLimit": 6, "validation": 1, "keyboardType": 4},
    EMAIL_PASSWORD_GO_ID: {"m_IsActive": False},
    TELEPHONE_GO_ID: {"m_IsActive": False},
    IDCARD_GO_ID: {"m_IsActive": False},
}

TARGET_PATHS = {
    -3075401596218027069: "Center/right/View/serviceView/RemindText",
    -1765947912211607504: "Center/right/View/serviceView/GoWebBtn/Sprite/Label (1)",
    4251692791884884092: "Center/right/View/serviceView/RemindText/Label (2)",
    EMAIL_TEXT_ID: "Center/right/View/userView/CnTable/Table/email/emailText",
    EMAIL_INPUT_ID: "Center/right/View/userView/CnTable/Table/email/Container/InputEmail",
    EMAIL_INPUT_LABEL_ID: "Center/right/View/userView/CnTable/Table/email/Container/InputEmail/Label",
    EMAIL_CODE_INPUT_ID: "Center/right/View/userView/CnTable/Table/email/Container/InputCode",
    EMAIL_CODE_TRANSFORM_ID: "Center/right/View/userView/CnTable/Table/email/Container/InputCode",
    EMAIL_CODE_SPRITE_ID: "Center/right/View/userView/CnTable/Table/email/Container/InputCode",
    EMAIL_BIND_WIDGET_ID: "Center/right/View/userView/CnTable/Table/email/Container/bindBtn",
    EMAIL_TEXT_TRANSFORM_ID: "Center/right/View/userView/CnTable/Table/email/emailText",
    EMAIL_CONTAINER_WIDGET_ID: "Center/right/View/userView/CnTable/Table/email/Container",
    EMAIL_TRANSFORM_ID: "Center/right/View/userView/CnTable/Table/email",
    PHONE_CONTAINER_TRANSFORM_ID: "Center/right/View/userView/CnTable/Table/telephone/Container",
    REWARD_GO_ID: "Center/right/View/userView/CnTable/Table/telephone/Container/Label",
    REWARD_TRANSFORM_ID: "Center/right/View/userView/CnTable/Table/telephone/Container/Label",
    REWARD_LABEL_ID: "Center/right/View/userView/CnTable/Table/telephone/Container/Label",
    REWARD_SPRITE_TRANSFORM_ID: "Center/right/View/userView/CnTable/Table/telephone/Container/Label/Sprite",
    EMAIL_PASSWORD_GO_ID: "Center/right/View/userView/CnTable/Table/email/Container/InputPassward",
    TELEPHONE_GO_ID: "Center/right/View/userView/CnTable/Table/telephone",
    IDCARD_GO_ID: "Center/right/View/userView/CnTable/Table/idCard",
}

PATCHED_TARGET_PATHS = dict(TARGET_PATHS)
for _path_id in (REWARD_GO_ID, REWARD_TRANSFORM_ID, REWARD_LABEL_ID):
    PATCHED_TARGET_PATHS[_path_id] = "Center/right/View/userView/CnTable/Table/email/EmailReward"
PATCHED_TARGET_PATHS[REWARD_SPRITE_TRANSFORM_ID] = (
    "Center/right/View/userView/CnTable/Table/email/EmailReward/Sprite"
)

REVIEWED_OBJECT_SHA256 = {
    -3075401596218027069: "dae9a42a7d2ecbeb4eef672a3635b621e297507635911d603ed07ad4fd2474bf",
    -1765947912211607504: "b551c09688a7373f685da8702a10b43785d577b8e8dad2484c2e8877ee6c728e",
    4251692791884884092: "5f663ee6e15466fc9d0faf08d58026e90b0c9830baac7c1de526f0dfa709af35",
    EMAIL_TEXT_ID: "40661a1a2cf5fb5b68271fd9052d32baf1804f20ed2d804c5fd8101388750df7",
    EMAIL_INPUT_ID: "61faee2184a0fa9a6dd20afbe06927b29b62e646aede8a7da8bf2b64c96f6e79",
    EMAIL_INPUT_LABEL_ID: "6336ad041663e76f463ee927d5a4505752ee13e7526b7c4f6df1884fabb9e4ff",
    EMAIL_CODE_INPUT_ID: "2620c6dc55c8e6db3fb23f625a4e3f6a5a36ab8c77ae0584ec36fa2930dd10da",
    EMAIL_PASSWORD_GO_ID: "876e04f43ed41fb42870788ed8243956677c7ea14a93d1434d64ed84c892e5a8",
    EMAIL_TRANSFORM_ID: "8899b9d84d07cea31b8eebf1ad35f92fb623b0e461b676714be30fa3f27c8718",
    EMAIL_TEXT_TRANSFORM_ID: "03ed6cb51e94c398031d82279dcd8d1e753346a481b08c2a230230e019f481d1",
    EMAIL_CODE_TRANSFORM_ID: "f477fb6eb74d4d96d313b6d2219e91c28543b8a41ea99ec96250482813c22423",
    EMAIL_CODE_SPRITE_ID: "a9d6146678468d3d68ed0917a7d9bc6697a93def6cd27a297ee260435ed64870",
    EMAIL_BIND_WIDGET_ID: "3c1da9565cbd4261ca400416f73e9e27cabc048c6c0d792bc45041aebb1e7601",
    EMAIL_CONTAINER_WIDGET_ID: "081a58c8780e3d2c8bb7517e807b732d0793d86154edc460990bc736e081eb7e",
    PHONE_CONTAINER_TRANSFORM_ID: "eb047491a73db084f96a478a947c16b10df2e37b2e6212b9589c0201485520b1",
    REWARD_GO_ID: "e58c34f36ca9562927557ecb8c20f5dbaa9cbd6e53eb3ae68ec29ab13b0e2811",
    REWARD_TRANSFORM_ID: "677d247f7771e452ce2cd7591cbc5acaffa3f02518b9ed87cd59f239f2fbdaa3",
    REWARD_LABEL_ID: "f351af4377836d167f56ef73632fa1d6e00048f8e895984ebcbd6370ad7aae6a",
    REWARD_SPRITE_ID: "bb62ab2386276f6c8d1b17df70ef1248d8e93aa1bb8c35a269a4113064b42461",
    REWARD_SPRITE_TRANSFORM_ID: "b4fcb6914c50891638def4ee2a37d4ecdc7382e4fc14c4247cb419fc5e67697b",
    TELEPHONE_GO_ID: "0058e1dea46e66598914554eb0b1f8b4afd34378c80d0c9c558d68183240df9e",
    IDCARD_GO_ID: "79e63353538156cfd843fa89ddb5da4d78094a368fb5353e2be8f5510a4643af",
    CONTROLLER_ID: "ed1ec3976804a59a5a8d961ab2581073063f29595f471f6b4dbb6086c67af512",
    EMAIL_COMPONENT_ID: "dc4fdd9c6c05a1707aa9e7ae0689bbd0c4eb42f8b838a0cd6134f399c7d4dd10",
    3698490786518340518: "79b7693f5205214245ff120a9ff7059111a66a2dfe037004e7c6a7ddcd225fe8",
    5130080117863922635: "c0898b07062ef034679e75d3f4449803058f89482abc5fef0495881ebebb29b7",
}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _object_index(environment):
    objects = {obj.path_id: obj for obj in environment.objects}
    if len(objects) != SOURCE_OBJECT_COUNT:
        raise ValueError("Settings prefab object count changed")
    return objects


def _hierarchy(objects, trees):
    parents = {}
    for path_id, obj in objects.items():
        if obj.type.name != "GameObject":
            continue
        transforms = [
            trees[ref["component"]["m_PathID"]]
            for ref in trees[path_id]["m_Component"]
            if objects[ref["component"]["m_PathID"]].type.name == "Transform"
        ]
        if len(transforms) != 1:
            raise ValueError("Settings GameObject transform changed")
        father_id = transforms[0]["m_Father"]["m_PathID"]
        parents[path_id] = trees.get(father_id, {}).get("m_GameObject", {}).get(
            "m_PathID", 0
        )
    paths = {}

    def resolve(path_id):
        if path_id not in paths:
            parent_id = parents[path_id]
            prefix = resolve(parent_id) + "/" if parent_id else ""
            paths[path_id] = prefix + trees[path_id]["m_Name"]
        return paths[path_id]

    for path_id in parents:
        resolve(path_id)
    return paths


def _verify_references(objects, trees, *, patched=False):
    controller = trees[CONTROLLER_ID]
    component_ids = [3698490786518340518, EMAIL_COMPONENT_ID, 5130080117863922635]
    if controller["m_Script"]["m_PathID"] != -4992533184044297428:
        raise ValueError("UserSettingControl script changed")
    if controller["components"] != [
        {"m_FileID": 0, "m_PathID": path_id} for path_id in component_ids
    ]:
        raise ValueError("UserSettingControl components reference changed")
    for type_id, component_id, gameobject_id in zip(
        range(3), component_ids, [TELEPHONE_GO_ID, EMAIL_GO_ID, IDCARD_GO_ID]
    ):
        component = trees[component_id]
        if (
            component["type"] != type_id
            or component["m_GameObject"] != {"m_FileID": 0, "m_PathID": gameobject_id}
            or component["m_Script"]["m_PathID"] != COMPONENT_SCRIPT_ID
        ):
            raise ValueError("UserSettingComponent type/GameObject reference changed")
    if trees[EMAIL_COMPONENT_ID]["text"] != {"m_FileID": 0, "m_PathID": EMAIL_TEXT_ID}:
        raise ValueError("Email text reference changed")
    if controller["remindText"] != {"m_FileID": 0, "m_PathID": -3075401596218027069}:
        raise ValueError("Service reminder reference changed")
    if controller["CnWidget"] != {"m_FileID": 0, "m_PathID": 2854484930089588976}:
        raise ValueError("CnTable reference changed")
    for field, path_id in {"EmailInputEm": EMAIL_INPUT_ID, "EmailInputCode": EMAIL_CODE_INPUT_ID,
                           "EmailInputPw": -4201656635629176416}.items():
        if controller[field] != {"m_FileID": 0, "m_PathID": path_id}:
            raise ValueError("Email input reference changed: " + field)
    if not trees[EMAIL_GO_ID]["m_IsActive"]:
        raise ValueError("Email entry is unexpectedly hidden")
    if trees[REWARD_SPRITE_ID]["mSpriteName"] != REWARD_ICON_NAME or (
        trees[REWARD_SPRITE_ID]["mAtlas"] != {"m_FileID": 7, "m_PathID": 2821308190926725452}
    ):
        raise ValueError("Original tarot reward icon/atlas changed")
    hierarchy = _hierarchy(objects, trees)
    prefix = "UserSettingPanel/"
    target_paths = PATCHED_TARGET_PATHS if patched else TARGET_PATHS
    for path_id, suffix in target_paths.items():
        tree = trees[path_id]
        go_id = tree.get("m_GameObject", {}).get("m_PathID", path_id)
        if hierarchy[go_id] != prefix + suffix:
            raise ValueError("Reviewed settings target hierarchy changed: " + suffix)
        if "mText" in PATCH_FIELDS[path_id]:
            if objects[path_id].type.name != "MonoBehaviour" or (
                tree["m_Script"]["m_PathID"] != LABEL_SCRIPT_ID
            ):
                raise ValueError("Reviewed settings target is no longer UILabel")


def patch(data: bytes) -> bytes:
    """Return patched usersettingpanel.ab bytes; never sign, save or deploy."""
    if len(data) != SOURCE_SIZE or sha(data) != SOURCE_SHA256:
        raise ValueError("Settings input differs from the reviewed original bundle")
    environment = UnityPy.load(data)
    objects = _object_index(environment)
    before = {path_id: obj.get_raw_data() for path_id, obj in objects.items()}
    for path_id, expected in REVIEWED_OBJECT_SHA256.items():
        if sha(before[path_id]) != expected:
            raise ValueError("Reviewed settings object changed: " + str(path_id))
    trees = {path_id: obj.read_typetree() for path_id, obj in objects.items()}
    _verify_references(objects, trees)
    patch_fields = copy.deepcopy(PATCH_FIELDS)
    reward_ref = {"m_FileID": 0, "m_PathID": REWARD_TRANSFORM_ID}
    phone_children = trees[PHONE_CONTAINER_TRANSFORM_ID]["m_Children"]
    assert phone_children.count(reward_ref) == 1, "Original reward parent changed"
    patch_fields[PHONE_CONTAINER_TRANSFORM_ID]["m_Children"] = [
        ref for ref in phone_children if ref != reward_ref
    ]
    email_children = trees[EMAIL_TRANSFORM_ID]["m_Children"]
    assert reward_ref not in email_children, "Reward already moved to email"
    patch_fields[EMAIL_TRANSFORM_ID]["m_Children"] = email_children + [reward_ref]
    expected_trees = {}
    for path_id, fields in patch_fields.items():
        tree = copy.deepcopy(trees[path_id])
        tree.update(fields)
        expected_trees[path_id] = tree
        objects[path_id].save_typetree(tree)
    result = environment.file.save(packer="original")
    reopened = UnityPy.load(result)
    after_objects = _object_index(reopened)
    after = {path_id: obj.get_raw_data() for path_id, obj in after_objects.items()}
    assert set(before) == set(after), "Settings object IDs changed"
    changed = {path_id for path_id in before if before[path_id] != after[path_id]}
    assert changed == set(PATCH_FIELDS), "Unrelated Unity objects changed"
    assert all(before[path_id] == after[path_id] for path_id in before if path_id not in PATCH_FIELDS), (
        "Non-target object raw bytes must remain identical"
    )
    after_trees = {path_id: obj.read_typetree() for path_id, obj in after_objects.items()}
    for path_id, expected in expected_trees.items():
        assert after_trees[path_id] == expected, "Unexpected target fields changed"
    _verify_references(after_objects, after_trees, patched=True)
    assert after_trees[EMAIL_TEXT_ID]["mWidth"] == 90
    assert after_trees[EMAIL_TEXT_ID]["mHeight"] == 26
    assert after_trees[EMAIL_CONTAINER_WIDGET_ID]["mHeight"] == 125
    assert after_trees[EMAIL_CODE_TRANSFORM_ID]["m_LocalPosition"]["y"] == -80.0
    code_widget = after_trees[EMAIL_CODE_SPRITE_ID]
    for side in ("leftAnchor", "rightAnchor", "bottomAnchor", "topAnchor"):
        assert code_widget[side]["target"] == {"m_FileID": 0, "m_PathID": EMAIL_INPUT_TRANSFORM_ID}
    assert code_widget["updateAnchors"] == 1  # Native UIRect.AnchorUpdate.OnUpdate.
    assert code_widget["mWidth"] == 156 and code_widget["mHeight"] == 50
    assert code_widget["topAnchor"]["absolute"] == -10
    assert code_widget["bottomAnchor"]["absolute"] == -60
    # Both native AnimForward email positions (-20/-40) keep a 10px edge gap
    # and 60px centre gap. The bind button stays centred on the same code row.
    for email_top in (-20, -40):
        email_bottom = email_top - 50
        code_top = email_bottom + code_widget["topAnchor"]["absolute"]
        code_bottom = email_bottom + code_widget["bottomAnchor"]["absolute"]
        assert email_bottom - code_top == 10 and code_top - code_bottom == 50
        assert (email_top + email_bottom - code_top - code_bottom) / 2 == 60
        bind_widget = after_trees[EMAIL_BIND_WIDGET_ID]
        assert bind_widget["topAnchor"]["target"] == code_widget["topAnchor"]["target"]
        assert bind_widget["bottomAnchor"]["target"] == code_widget["bottomAnchor"]["target"]
        assert bind_widget["topAnchor"]["absolute"] + bind_widget["bottomAnchor"]["absolute"] == -70
    assert after_trees[REWARD_LABEL_ID]["mText"] == "×100"
    assert after_trees[TELEPHONE_GO_ID]["m_IsActive"] is False
    assert after_trees[IDCARD_GO_ID]["m_IsActive"] is False
    assert after_trees[EMAIL_PASSWORD_GO_ID]["m_IsActive"] is False
    assert after_trees[EMAIL_INPUT_ID]["m_Enabled"] == 0
    assert after_trees[EMAIL_CODE_INPUT_ID]["characterLimit"] == 6
    return result


patch_settings_prefab = patch


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=SOURCE_BUNDLE)
    parser.add_argument("--output", type=Path, help="Optional explicit patched bundle path")
    args = parser.parse_args()
    result = patch(args.input.read_bytes())
    if args.output:
        args.output.write_bytes(result)
    print(json.dumps({
        "assetPath": ASSET_PATH,
        "sourceSha256": SOURCE_SHA256,
        "patchedSha256": sha(result),
        "patchedSize": len(result),
        "objects": SOURCE_OBJECT_COUNT,
        "changedObjects": len(PATCH_FIELDS),
        "unchangedRawObjects": SOURCE_OBJECT_COUNT - len(PATCH_FIELDS),
        "phoneAndRealNameHidden": True,
        "emailRewardSlot": True,
        "emailRewardItemId": 40350003,
        "emailRewardIcon": REWARD_ICON_NAME,
        "emailCodeRowY": -80,
        "emailRowCentreGap": 60,
        "emailCodeAnchoredToEmail": True,
        "emailNotice": EMAIL_TEXT,
        "output": str(args.output) if args.output else None,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
