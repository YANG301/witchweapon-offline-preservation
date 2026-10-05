"""Lower original client feature-entry level gates without changing progression.

The original Constant CSV is XOR-0xff encoded in one Unity MonoBehaviour.
Only the reviewed ``value3`` rows below are changed. Chapter completion,
tutorial state, resource costs, guild permissions and level-up curves remain
the server's and original client's normal responsibility.
"""

import codecs

import UnityPy


# Key -> original value3. A value of 1 is also accepted for repeatable builds.
SINGLE_CHANNEL_GATES = {
    "CORE_INSTANCE_MIN_LEVEL": 27,
    "METHOD_OPEN_LEVEL_BUDOKAN": 10,
    "METHOD_OPEN_LEVEL_WITCH_TRIAL": 20,
    "METHOD_OPEN_LEVEL_CHAPTER2": 5,
    "METHOD_OPEN_LEVEL_CHAPTER3": 15,
    "METHOD_OPEN_LEVEL_CHAPTER4": 22,
    "METHOD_OPEN_LEVEL_CHAPTER5": 25,
    "METHOD_OPEN_LEVEL_CHAPTER6": 30,
    "METHOD_OPEN_LEVEL_CHAPTER7": 33,
    "METHOD_OPEN_LEVEL_CHAPTER8": 36,
    "ASSOCIATION_CREATE_LEVEL": 20,
    "ASSOCIATION_ENTER_LEVEL": 15,
    "ACTIVITY_GAMES_MIN_LEVEL": 15,
    "ACTIVITY_GAMES_RULE5_UPPER_UNLOCK_MIN_LEVEL": 30,
    "ACTIVITY_MAINPAGE_MISSION_LEVEL": 12,
}

CHAT_LEVELS = {
    "CHAT_SPEAK_LEVEL": {22: 20, 25: 20, 50: 20, 60: 20, 70: 8, 80: 8},
    "CHAT_CAN_SEE_LEVEL": {22: 15, 25: 15, 50: 15, 60: 15, 70: 8, 80: 8},
}

# The original InstanceSet table has distinct level gates as well as
# ``front_instance`` chapter prerequisites. Only the former are lowered.
INSTANCE_ENTER_LEVELS = {
    "3010002": 5, "3010003": 12, "3010004": 20, "3010005": 25,
    "3010006": 30, "3010007": 33, "3010008": 36, "3010009": 40,
    "3010010": 43, "3010011": 47, "3010012": 50, "3010013": 54,
    "3010014": 58, "3010015": 63, "3010016": 66,
    "3020001": 20, "3020002": 20, "3020003": 20, "3020004": 20,
    "3020005": 10, "3020006": 10, "3020007": 10,
    "3030001": 27, "3060001": 30, "3060002": 30, "3060003": 30,
}


def patch_constant_text(text):
    """Return a checked, minimally changed CSV text (including line endings)."""
    if not text.startswith("ID,value1,value2,value3,value4,channel_group,"):
        raise ValueError("Unexpected Constant CSV header")
    seen = set()
    output = []
    changed = 0
    for line in text.splitlines(keepends=True):
        payload = line.rstrip("\r\n")
        columns = payload.split(",")
        if len(columns) < 6:
            output.append(line)
            continue
        key = columns[0]
        if key in SINGLE_CHANNEL_GATES or key in CHAT_LEVELS:
            try:
                channel = int(columns[5])
                old = int(columns[3])
            except ValueError as error:
                raise ValueError("Malformed level gate: " + key) from error
            if key in SINGLE_CHANNEL_GATES:
                if channel != 0:
                    raise ValueError("Unexpected level gate channel: " + key)
                expected = SINGLE_CHANNEL_GATES[key]
            else:
                expected = CHAT_LEVELS[key].get(channel)
                if expected is None:
                    raise ValueError("Unexpected chat level gate channel: " + key)
            identity = (key, channel)
            if identity in seen:
                raise ValueError("Duplicate level gate: " + key)
            seen.add(identity)
            if old not in (expected, 1):
                raise ValueError("Unexpected level gate value: " + key)
            if old != 1:
                columns[3] = "1"
                payload = ",".join(columns)
                line = payload + line[len(line.rstrip("\r\n")):]
                changed += 1
        output.append(line)
    expected_rows = {(key, 0) for key in SINGLE_CHANNEL_GATES}
    expected_rows.update((key, channel) for key, channels in CHAT_LEVELS.items()
                         for channel in channels)
    if seen != expected_rows:
        raise ValueError("Constant CSV level gate set is incomplete")
    result = "".join(output)
    if len(result.splitlines()) != len(text.splitlines()):
        raise ValueError("Constant CSV row count changed")
    return result, changed


def patch_instance_set_text(text):
    """Lower only reviewed InstanceSet entry levels; retain route prerequisites."""
    lines = text.splitlines(keepends=True)
    if not lines:
        raise ValueError("Empty InstanceSet CSV")
    header = lines[0].rstrip("\r\n").split(",")
    if header[:1] != ["ID"] or "instance_set_enter_level" not in header or \
            "front_instance" not in header or "instance_set_sweep_level" not in header:
        raise ValueError("Unexpected InstanceSet CSV header")
    id_column = header.index("ID")
    entry_column = header.index("instance_set_enter_level")
    seen = set()
    output = [lines[0]]
    changed = 0
    for line in lines[1:]:
        payload = line.rstrip("\r\n")
        columns = payload.split(",")
        if len(columns) != len(header):
            raise ValueError("Malformed InstanceSet CSV row")
        row_id = columns[id_column]
        raw_level = columns[entry_column]
        if row_id in INSTANCE_ENTER_LEVELS:
            if row_id in seen:
                raise ValueError("Duplicate InstanceSet level gate: " + row_id)
            seen.add(row_id)
            try:
                old = int(raw_level)
            except ValueError as error:
                raise ValueError("Malformed InstanceSet level gate: " + row_id) from error
            if old not in (INSTANCE_ENTER_LEVELS[row_id], 1):
                raise ValueError("Unexpected InstanceSet level gate: " + row_id)
            if old != 1:
                columns[entry_column] = "1"
                line = ",".join(columns) + line[len(payload):]
                changed += 1
        elif row_id.isdigit() and raw_level.isdigit() and int(raw_level) > 1:
            raise ValueError("Unreviewed InstanceSet level gate: " + row_id)
        output.append(line)
    if seen != set(INSTANCE_ENTER_LEVELS):
        raise ValueError("InstanceSet level gate set is incomplete")
    result = "".join(output)
    if len(result.splitlines()) != len(text.splitlines()):
        raise ValueError("InstanceSet CSV row count changed")
    return result, changed


def _csv_tree(raw, name):
    env = UnityPy.load(raw)
    objects = [item for item in env.objects if item.type.name == "MonoBehaviour"]
    if len(objects) != 1:
        raise ValueError("Expected one " + name + " MonoBehaviour")
    item = objects[0]
    tree = item.read_typetree()
    if tree.get("m_Name") != name or tree.get("isEncrypt") != 1 or \
            not isinstance(tree.get("bytes"), list):
        raise ValueError("Unexpected " + name + " serialization")
    encoded = bytes(byte ^ 255 for byte in tree["bytes"])
    has_bom = encoded.startswith(codecs.BOM_UTF8)
    return env, item, tree, encoded.decode("utf-8-sig"), has_bom


def _constant_tree(raw):
    return _csv_tree(raw, "Constant")


def _instance_set_tree(raw):
    return _csv_tree(raw, "InstanceSet")


def patch_bundle(raw):
    """Patch a Constant asset bundle; return identical bytes if already patched.

    The caller must also update the APK asset index entry for
    ``/config/clientexel/constant.ab`` before signing the APK.
    """
    env, item, tree, old, has_bom = _constant_tree(raw)
    updated, changed = patch_constant_text(old)
    if changed == 0:
        return raw
    encoded = (codecs.BOM_UTF8 if has_bom else b"") + updated.encode("utf-8")
    tree["bytes"] = list(byte ^ 255 for byte in encoded)
    item.save_typetree(tree)
    result = env.file.save(packer="original")
    _, _, _, readback, readback_bom = _constant_tree(result)
    if readback != updated or readback_bom != has_bom:
        raise ValueError("Patched Constant bundle failed round-trip verification")
    return result


def patch_instance_set_bundle(raw):
    """Patch InstanceSet entry levels; return identical bytes if already patched.

    The caller must update the APK asset index entry for
    ``/config/clientexel/instanceset.ab`` before signing the APK.
    """
    env, item, tree, old, has_bom = _instance_set_tree(raw)
    updated, changed = patch_instance_set_text(old)
    if changed == 0:
        return raw
    encoded = (codecs.BOM_UTF8 if has_bom else b"") + updated.encode("utf-8")
    tree["bytes"] = list(byte ^ 255 for byte in encoded)
    item.save_typetree(tree)
    result = env.file.save(packer="original")
    _, _, _, readback, readback_bom = _instance_set_tree(result)
    if readback != updated or readback_bom != has_bom:
        raise ValueError("Patched InstanceSet bundle failed round-trip verification")
    return result
