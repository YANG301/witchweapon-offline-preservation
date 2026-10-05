"""Hide compatibility stock badges for truly unlimited original shop goods."""
from __future__ import annotations

import hashlib

import UnityPy


INPUT_BUNDLE_SHA = "4255fb381513e113a6ab2a0e1ae7482f7614e6a7a02437bd17382b9ee1e84271"
INPUT_SCRIPT_SHA = "1351960586587ad1b48e775d22b82a60127845fe96ec0def1550095d5eedf2f1"
ANCHOR = """        if setID ~= '47000004' and setID ~= '47000020' then
            local fresh = field(shopType, 'FreshView', shop)
            if fresh ~= nil and fresh.gameObject.activeSelf then
                fresh.gameObject:SetActive(false)
            end
        end
"""
ADD = """        -- These shelves have no per-item limit. The protocol still carries a
        -- positive compatibility Number; never present it as actual stock.
        local innerSet = tostring(field(shopType, 'currentSetID', shop))
        local unlimited = setID == '47000003' or setID == '47000008' or
            (setID == '47000005' and innerSet == '44000002') or
            (setID == '47000024' and innerSet == '44000016')
        if unlimited then
            local grid = field(shopType, 'currentGrid', shop)
            if grid ~= nil then
                local transform = grid.transform
                for index = 0, transform.childCount - 1 do
                    local badge = transform:GetChild(index):Find('Mid/Num')
                    if badge ~= nil and badge.gameObject.activeSelf then
                        badge.gameObject:SetActive(false)
                    end
                end
            end
        end
"""


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def patch(raw: bytes) -> bytes:
    if digest(raw) != INPUT_BUNDLE_SHA:
        raise ValueError("Unreviewed v101 shop Lua bundle")
    bundle = UnityPy.load(raw)
    before = {obj.path_id: digest(obj.get_raw_data()) for obj in bundle.objects}
    matches = [obj for obj in bundle.objects if obj.type.name == "TextAsset" and
               obj.read_typetree().get("m_Name") == "init.lua"]
    if len(matches) != 1:
        raise ValueError("Expected exactly one shop init script")
    target = matches[0]
    tree = target.read_typetree()
    source = tree.get("m_Script")
    if (not isinstance(source, str) or digest(source.encode("utf-8")) != INPUT_SCRIPT_SHA
            or source.count(ANCHOR) != 1 or ADD in source):
        raise ValueError("Unreviewed stock badge location")
    updated = source.replace(ANCHOR, ANCHOR + ADD, 1)
    tree["m_Script"] = updated
    target.save_typetree(tree)
    result = bundle.file.save(packer="original")
    decoded = UnityPy.load(result)
    changed = {obj.path_id for obj in decoded.objects
               if digest(obj.get_raw_data()) != before[obj.path_id]}
    scripts = [obj.read_typetree().get("m_Script") for obj in decoded.objects
               if obj.path_id == target.path_id]
    if changed != {target.path_id} or scripts != [updated]:
        raise ValueError("Unlimited stock patch changed unrelated objects")
    return result
