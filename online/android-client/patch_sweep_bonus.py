"""Restore original sweep type and parameter in the temporary MobList."""

from patch_simple_campaign import (
    CHAPTER16_IDS, MAINLINE_IDS, ORIGINAL_DUPLICATE_MOB_IDS, _csv_tree, _patch,
)


def _original_bonus_values(text: str) -> dict[str, tuple[str, str]]:
    header = text.splitlines()[0].split(",")
    if header[:5] != ["ID", "mapID", "instObjectiveType", "instBonusType",
                      "intstBonusParam"]:
        raise ValueError("Unexpected original MobList header")
    values = {}
    duplicates = set()
    for line in text.splitlines()[1:]:
        columns = line.split(",")
        identity = columns[0]
        if identity in MAINLINE_IDS:
            if len(columns) < 5 or columns[3] not in {"0", "1", "2", "3", "4"}:
                raise ValueError("Invalid original sweep type: " + identity)
            if identity in values:
                if identity not in ORIGINAL_DUPLICATE_MOB_IDS or identity in duplicates:
                    raise ValueError("Unexpected original duplicate stage: " + identity)
                duplicates.add(identity)
            else:
                # The original chapter-12 table contains five duplicate IDs;
                # the existing type patch chose the first row for each ID.
                values[identity] = (columns[3], columns[4])
    if (set(values) != MAINLINE_IDS - CHAPTER16_IDS or
            duplicates != ORIGINAL_DUPLICATE_MOB_IDS or
            values["3110001002"] != ("2", "0.5")):
        raise ValueError("Unexpected original MobList mainline coverage")
    return values


def patch_sweep_bonus_text(current: str, original: str) -> str:
    targets = _original_bonus_values(original)
    lines = current.splitlines(keepends=True)
    header = lines[0].rstrip("\r\n").split(",") if lines else []
    if header[:5] != ["ID", "mapID", "instObjectiveType", "instBonusType",
                      "intstBonusParam"]:
        raise ValueError("Unexpected temporary MobList header")
    seen, output = set(), []
    for line in lines:
        content = line.rstrip("\r\n")
        columns = content.split(",")
        identity = columns[0]
        if identity in MAINLINE_IDS:
            if identity in seen or len(columns) != len(header):
                raise ValueError("Duplicate or malformed temporary MobList row: " + identity)
            seen.add(identity)
            if identity in targets:
                expected_type, expected_param = targets[identity]
                if columns[3] not in {"0", expected_type}:
                    raise ValueError("Unreviewed sweep type already present: " + identity)
                if columns[4] not in {"0", expected_param}:
                    raise ValueError("Unreviewed sweep parameter already present: " + identity)
                columns[3], columns[4] = expected_type, expected_param
                line = ",".join(columns) + line[len(content):]
            # Chapter 16 has no original MobList. Preserve its temporary
            # template exactly, including its deliberately simplified param.
        output.append(line)
    if seen != MAINLINE_IDS:
        raise ValueError("Temporary MobList has incomplete mainline coverage")
    return "".join(output)


def patch_sweep_bonus_bundle(current_raw: bytes, original_raw: bytes) -> bytes:
    _, _, _, original, _ = _csv_tree(original_raw, "InstanceMobList")
    return _patch(current_raw, "InstanceMobList",
                  lambda current: patch_sweep_bonus_text(current, original))
