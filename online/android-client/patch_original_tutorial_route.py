"""Select the preserved base-station onboarding route in LessonTrigger.ab.

The shipped APK contains both tutorial generations.  The newer trigger table
selects lesson14001 -> stage 3150001004 -> lesson01001; the older preserved
route is lesson10001 -> stage 3150001001 -> lesson00001.  Only records 1 and 2
are changed.  Their source lessons and map remain original APK assets.
"""

from __future__ import annotations

import codecs

import UnityPy


HEADER = ("recID,nextID,localPrefID,quest1,quest2,quest3,fileSuffixName,"
          "storyID,storyGroupID,uiEvtType,uiEvtParam,roleLvConstrain,"
          "channel_group,comment")
ROUTE = {
    "1": {"fileSuffixName": ("14001", "10001"),
          "uiEvtType": ("EnterInitialGuideScene", "EnterInitialGuideScene")},
    "2": {"quest1": ("509021001", "509005002"),
          "fileSuffixName": ("01001", "00001"),
          "uiEvtType": ("PreCombatBegin", "PreCombatBegin"),
          "uiEvtParam": ("3150001004", "3150001001")},
}


def patch_csv(text: str) -> str:
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].rstrip("\r\n") != HEADER:
        raise ValueError("Unexpected LessonTrigger CSV header")
    columns = HEADER.split(",")
    seen: set[str] = set()
    output: list[str] = []
    for line in lines:
        payload = line.rstrip("\r\n")
        values = payload.split(",")
        record = values[0]
        if record not in ROUTE or len(values) != len(columns):
            output.append(line)
            continue
        if record in seen:
            raise ValueError("Duplicate tutorial trigger record " + record)
        seen.add(record)
        for field, (old, new) in ROUTE[record].items():
            index = columns.index(field)
            if values[index] not in (old, new):
                raise ValueError("Unexpected tutorial trigger " + record + "." + field)
            values[index] = new
        output.append(",".join(values) + line[len(payload):])
    if seen != set(ROUTE):
        raise ValueError("Tutorial trigger records are missing")
    result = "".join(output)
    if len(result.splitlines()) != len(text.splitlines()):
        raise ValueError("Tutorial trigger row count changed")
    return result


def _read(raw: bytes):
    env = UnityPy.load(raw)
    objects = [obj for obj in env.objects if obj.type.name == "MonoBehaviour"]
    if len(objects) != 1:
        raise ValueError("LessonTrigger bundle must contain one MonoBehaviour")
    obj = objects[0]
    tree = obj.read_typetree()
    if tree.get("m_Name") != "LessonTrigger" or tree.get("isEncrypt") != 1 \
            or not isinstance(tree.get("bytes"), list):
        raise ValueError("Unexpected LessonTrigger asset")
    decoded = bytes(byte ^ 255 for byte in tree["bytes"])
    return env, obj, tree, decoded.decode("utf-8-sig"), \
        decoded.startswith(codecs.BOM_UTF8)


def patch_bundle(raw: bytes) -> bytes:
    env, obj, tree, old, had_bom = _read(raw)
    updated = patch_csv(old)
    if updated == old:
        return raw
    data = (codecs.BOM_UTF8 if had_bom else b"") + updated.encode("utf-8")
    tree["bytes"] = [byte ^ 255 for byte in data]
    obj.save_typetree(tree)
    result = env.file.save(packer="original")
    _, _, _, readback, readback_bom = _read(result)
    if readback != updated or readback_bom != had_bom:
        raise ValueError("Tutorial bundle round-trip verification failed")
    return result
