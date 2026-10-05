"""Keep the Unity updater launcher and declare the dormant legacy QQ SDK activities.

The old Unity Activity still initializes Tencent's SDK even though online QQ
login is hidden. Its manifest check requires both classes to be declared.
These declarations are deliberately not exported and have no deep-link filter.
"""

from __future__ import annotations

import struct

import patch_manifest as axml


PACKAGE = "com.codex.witchweapon.online.originalui.test"
OLD_VERSION_CODE = 20043084
NEW_VERSION_CODE = 20043085
OLD_VERSION_NAME = "2.0.1.20043084"
NEW_VERSION_NAME = "2.0.1.20043085"
BOOTSTRAP = "com.codex.witchweapon.UpdateBootstrapActivity"
AUTH = "com.tencent.tauth.AuthActivity"
ASSIST = "com.tencent.connect.common.AssistActivity"


def activity_names(chunks: list[bytearray], strings: list[str]) -> list[str]:
    return [axml.attribute_value(chunk, axml.attributes(chunk, strings)["name"], strings)
            for chunk in chunks if axml.start_tag(chunk, strings) == "activity"]


def patch(raw: bytes) -> bytes:
    chunks = axml.split_chunks(raw)
    strings, pool_info = axml.string_pool(chunks[0])
    manifest = next(chunk for chunk in chunks
                    if axml.start_tag(chunk, strings) == "manifest")
    root_attrs = axml.attributes(manifest, strings)
    if axml.attribute_value(manifest, root_attrs["package"], strings) != PACKAGE:
        raise ValueError("Unexpected Android package")
    if axml.attribute_value(manifest, root_attrs["versionName"], strings) != OLD_VERSION_NAME:
        raise ValueError("Unexpected Android version name")
    version_at = root_attrs["versionCode"]
    if manifest[version_at + 15] != 0x10 or axml.u32(manifest, version_at + 16) != OLD_VERSION_CODE:
        raise ValueError("Unexpected Android version code")
    struct.pack_into("<I", manifest, version_at + 16, NEW_VERSION_CODE)
    axml.assign_string(manifest, root_attrs["versionName"], NEW_VERSION_NAME, strings)

    names = activity_names(chunks, strings)
    if names.count(BOOTSTRAP) != 1 or AUTH in names or ASSIST in names:
        raise ValueError("Unexpected Activity inventory")
    bootstrap = next(chunk for chunk in chunks
                     if axml.start_tag(chunk, strings) == "activity"
                     and axml.attribute_value(chunk, axml.attributes(chunk, strings)["name"], strings)
                     == BOOTSTRAP)
    bootstrap_end = chunks[axml.paired_end(chunks, chunks.index(bootstrap), strings)]
    dormant_activities: list[bytearray] = []
    for name in (AUTH, ASSIST):
        start = bytearray(bootstrap)
        attrs = axml.attributes(start, strings)
        axml.assign_string(start, attrs["name"], name, strings)
        exported = attrs.get("exported")
        if exported is None or start[exported + 15] != 0x12:
            raise ValueError("Bootstrap exported attribute is not a boolean")
        struct.pack_into("<I", start, exported + 16, 0)
        dormant_activities.extend((start, bytearray(bootstrap_end)))

    application_at = next(index for index, chunk in enumerate(chunks)
                          if axml.start_tag(chunk, strings) == "application")
    application_end = axml.paired_end(chunks, application_at, strings)
    chunks[application_end:application_end] = dormant_activities
    pool = axml.serialize_pool(chunks[0], strings, pool_info)
    body = pool + b"".join(bytes(chunk) for chunk in chunks[1:])
    result = struct.pack("<HHI", 3, 8, len(body) + 8) + body

    checked = axml.split_chunks(result)
    checked_strings, _ = axml.string_pool(checked[0])
    actual = activity_names(checked, checked_strings)
    if len(actual) != len(names) + 2 or actual.count(AUTH) != 1 or actual.count(ASSIST) != 1:
        raise ValueError("Tencent Activity declarations did not round-trip")
    for chunk in checked:
        if axml.start_tag(chunk, checked_strings) not in ("activity",):
            continue
        attrs = axml.attributes(chunk, checked_strings)
        name = axml.attribute_value(chunk, attrs["name"], checked_strings)
        if name in (AUTH, ASSIST):
            exported = attrs["exported"]
            if chunk[exported + 15] != 0x12 or axml.u32(chunk, exported + 16) != 0:
                raise ValueError("Dormant Tencent Activity was exported")
    checked_root = next(chunk for chunk in checked
                        if axml.start_tag(chunk, checked_strings) == "manifest")
    checked_attrs = axml.attributes(checked_root, checked_strings)
    if (axml.u32(checked_root, checked_attrs["versionCode"] + 16) != NEW_VERSION_CODE
            or axml.attribute_value(checked_root, checked_attrs["versionName"], checked_strings)
            != NEW_VERSION_NAME):
        raise ValueError("Updated Android version did not round-trip")
    return result
