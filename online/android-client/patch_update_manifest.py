"""Add the update bootstrap launcher to the existing original-UI APK.

The package name and the Unity Activity are deliberately preserved so this
APK can replace the existing player build without clearing Android app data.
"""

from __future__ import annotations

import struct

import patch_manifest as axml


PACKAGE = "com.codex.witchweapon.online.originalui.test"
GAME = axml.GAME
UPDATE = "com.codex.witchweapon.UpdateBootstrapActivity"
LABEL = "魔女兵器·新丰洲"
OLD_VERSION_CODE = 20043077
NEW_VERSION_CODE = 20043083
VERSION_NAME = "2.0.1.20043083"


def _name(chunk: bytearray, strings: list[str]) -> str:
    attrs = axml.attributes(chunk, strings)
    return axml.attribute_value(chunk, attrs["name"], strings)


def _launcher_filter(block: list[bytearray], strings: list[str]) -> bool:
    if axml.start_tag(block[0], strings) != "intent-filter":
        return False
    actions: set[str] = set()
    categories: set[str] = set()
    for child in axml.direct_children(block, strings):
        tag = axml.start_tag(child[0], strings)
        if tag not in ("action", "category"):
            continue
        value = _name(child[0], strings)
        (actions if tag == "action" else categories).add(value)
    return ("android.intent.action.MAIN" in actions
            and "android.intent.category.LAUNCHER" in categories)


def _launchers(chunks: list[bytearray], strings: list[str]) -> list[str]:
    result: list[str] = []
    for index, chunk in enumerate(chunks):
        if axml.start_tag(chunk, strings) != "activity":
            continue
        name = _name(chunk, strings)
        block = chunks[index:axml.paired_end(chunks, index, strings) + 1]
        if any(_launcher_filter(child, strings)
               for child in axml.direct_children(block, strings)):
            result.append(name)
    return result


def patch(raw: bytes) -> bytes:
    chunks = axml.split_chunks(raw)
    strings, pool_info = axml.string_pool(chunks[0])
    if _launchers(chunks, strings) != [GAME]:
        raise ValueError("Expected the original Unity Activity as the sole launcher")

    manifest = next((chunk for chunk in chunks
                     if axml.start_tag(chunk, strings) == "manifest"), None)
    if manifest is None:
        raise ValueError("Manifest start tag missing")
    root_attrs = axml.attributes(manifest, strings)
    if axml.attribute_value(manifest, root_attrs["package"], strings) != PACKAGE:
        raise ValueError("Unexpected APK package; an in-place update is impossible")
    version_at = root_attrs["versionCode"]
    if (manifest[version_at + 15] != 0x10
            or axml.u32(manifest, version_at + 16) != OLD_VERSION_CODE):
        raise ValueError("Unexpected Android versionCode")
    struct.pack_into("<I", manifest, version_at + 16, NEW_VERSION_CODE)
    axml.assign_string(manifest, root_attrs["versionName"], VERSION_NAME, strings)

    game_at = [index for index, chunk in enumerate(chunks)
               if axml.start_tag(chunk, strings) == "activity"
               and _name(chunk, strings) == GAME]
    if len(game_at) != 1:
        raise ValueError("Expected one Unity Activity")
    game_at = game_at[0]
    game_end = axml.paired_end(chunks, game_at, strings)
    game_block = chunks[game_at:game_end + 1]
    game_children = axml.direct_children(game_block, strings)
    launcher = [child for child in game_children if _launcher_filter(child, strings)]
    if len(launcher) != 1:
        raise ValueError("Expected one Unity launcher intent-filter")

    # Preserve the Unity Activity and all its attributes/other child elements.
    # Its launcher filter moves to the new bootstrap Activity verbatim.
    game_result = [game_block[0]]
    for child in game_children:
        if child is not launcher[0]:
            game_result.extend(child)
    game_result.append(game_block[-1])

    update_start = bytearray(game_block[0])
    update_attrs = axml.attributes(update_start, strings)
    axml.assign_string(update_start, update_attrs["name"], UPDATE, strings)
    if "label" in update_attrs:
        axml.assign_string(update_start, update_attrs["label"], LABEL, strings)
    exported_at = update_attrs.get("exported")
    if exported_at is None:
        axml.add_exported_true(update_start, strings)
    elif update_start[exported_at + 15] != 0x12 or axml.u32(update_start, exported_at + 16) != 1:
        raise ValueError("Unexpected Unity Activity exported flag")
    update_result = [update_start, *launcher[0], game_block[-1]]

    output: list[bytearray] = []
    index = 1
    while index < len(chunks):
        if index == game_at:
            output.extend(game_result)
            output.extend(update_result)
            index = game_end + 1
            continue
        chunk = chunks[index]
        if axml.start_tag(chunk, strings) == "application":
            attrs = axml.attributes(chunk, strings)
            if "label" in attrs:
                axml.assign_string(chunk, attrs["label"], LABEL, strings)
        output.append(chunk)
        index += 1

    pool = axml.serialize_pool(chunks[0], strings, pool_info)
    body = pool + b"".join(bytes(chunk) for chunk in output)
    result = struct.pack("<HHI", 3, 8, len(body) + 8) + body

    verified = axml.split_chunks(result)
    verified_strings, _ = axml.string_pool(verified[0])
    if _launchers(verified, verified_strings) != [UPDATE]:
        raise ValueError("Update Activity is not the sole launcher")
    actual_activities = [_name(chunk, verified_strings) for chunk in verified
                         if axml.start_tag(chunk, verified_strings) == "activity"]
    if actual_activities.count(GAME) != 1 or actual_activities.count(UPDATE) != 1:
        raise ValueError("Unity or update Activity declaration is inconsistent")
    root = next(chunk for chunk in verified
                if axml.start_tag(chunk, verified_strings) == "manifest")
    root_attrs = axml.attributes(root, verified_strings)
    if (axml.u32(root, root_attrs["versionCode"] + 16) != NEW_VERSION_CODE
            or axml.attribute_value(root, root_attrs["versionName"], verified_strings)
            != VERSION_NAME):
        raise ValueError("Android version fields did not survive serialization")
    return result
