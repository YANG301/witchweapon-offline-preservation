"""Remove entry gates from exactly the original 235 mainline stages / 16 chapters.

The server must send Level.Status=true for every stage. Do not fake IsClear,
stars, rewards, or story playback. Chapter prerequisites only read UnLocok,
so the original front_instance / instance_set_next graph must remain intact.
Clearing front_instance alone is unsafe: GameDataHelper.InitData inserts its
zero value into InstanceSetToFrontInstance and IsInstanceSetUnlock then tries
to read level 0.
"""

from patch_simple_campaign import MAINLINE_IDS, _patch


CHAPTER_IDS = frozenset(str(3010000 + chapter) for chapter in range(1, 17))
ORIGINAL_STAGE_LEVELS = {1: 1, 2: 5, 3: 12, 4: 17, 5: 21}
ORIGINAL_CHAPTER_LEVELS = (0, 5, 12, 20, 25, 30, 33, 36, 40, 43, 47, 50, 54, 58, 63, 66)
ORIGINAL_RESTRICTIONS = {"3110001005": "102", "3110001007": "103", "3110001009": "104"}


def _patch_rows(text, identities, required_columns, allowed_columns, update):
    lines = text.splitlines(keepends=True)
    header = lines[0].rstrip("\r\n").split(",") if lines else []
    if not header or header[0] != "ID" or len(set(header)) != len(header) or \
            not set(required_columns) <= set(header):
        raise ValueError("Unexpected campaign table header")
    columns = {name: header.index(name) for name in required_columns}
    editable = {header.index(name) for name in allowed_columns}
    seen, output = set(), []
    for line in lines:
        content = line.rstrip("\r\n")
        row = content.split(",")
        identity = row[0]
        if identity in identities:
            if identity in seen or len(row) != len(header):
                raise ValueError("Duplicate or malformed campaign row: " + identity)
            seen.add(identity)
            before = list(row)
            update(identity, row, columns)
            if any(a != b and i not in editable for i, (a, b) in enumerate(zip(before, row))):
                raise ValueError("Unexpected campaign field changed: " + identity)
            line = ",".join(row) + line[len(content):]
        output.append(line)
    if seen != identities:
        raise ValueError("Campaign row set incomplete")
    result = "".join(output)
    if len(result.splitlines(keepends=True)) != len(lines):
        raise ValueError("Campaign row count changed")
    for before, after in zip(lines, result.splitlines(keepends=True)):
        if before.split(",", 1)[0] not in identities and before != after:
            raise ValueError("Unrelated campaign table row changed")
    return result


def patch_instance_text(text: str) -> str:
    fields = ("instance_set_attached", "instance_type", "instance_enter_level",
              "instance_restrict", "need_story", "unlock_story",
              "instance_enter_limit", "instance_stamina_enter", "instance_stamina_victory")

    def update(identity, row, columns):
        chapter = (int(identity) - 3110000000) // 1000
        stage = int(identity) % 1000
        expected_type = "2" if stage <= 10 else "3"
        if row[columns["instance_set_attached"]] != str(3010000 + chapter) or \
                row[columns["instance_type"]] != expected_type:
            raise ValueError("Unexpected mainline stage identity: " + identity)
        level_column = columns["instance_enter_level"]
        if row[level_column] not in (str(ORIGINAL_STAGE_LEVELS.get(chapter, 25)), "1"):
            raise ValueError("Unexpected mainline entry level: " + identity)
        row[level_column] = "1"
        restriction_column = columns["instance_restrict"]
        restriction = row[restriction_column]
        if restriction not in ("", "0", ORIGINAL_RESTRICTIONS.get(identity, "")):
            raise ValueError("Unreviewed mainline team restriction: " + identity)
        if restriction not in ("", "0"):
            row[restriction_column] = "0"
        # All 235 source rows already have no story prerequisite. Keep their
        # existing zero representation rather than making a cosmetic rewrite.
        # unlock_story is a separate field; never erase or pre-complete it.
        if row[columns["need_story"]] not in ("", "0"):
            raise ValueError("Unexpected mainline story prerequisite: " + identity)

    return _patch_rows(text, MAINLINE_IDS, fields,
                       ("instance_enter_level", "instance_restrict"), update)


def patch_instance_set_text(text: str) -> str:
    fields = ("instance_set_type", "instance_set_enter_level", "instance_set_next",
              "front_instance", "first_instance", "instance_set_enter_limit")

    def update(identity, row, columns):
        chapter = int(identity) - 3010000
        if row[columns["instance_set_type"]] != "1":
            raise ValueError("Unexpected mainline chapter type: " + identity)
        level_column = columns["instance_set_enter_level"]
        original = ORIGINAL_CHAPTER_LEVELS[chapter - 1]
        if row[level_column] not in (str(original), "1"):
            raise ValueError("Unexpected chapter entry level: " + identity)
        if int(row[level_column]) > 1:
            row[level_column] = "1"
        # Retain this graph exactly. Native InitData builds next -> front from
        # it; IsInstanceSetUnlock checks that level's UnLocok, not IsClear.
        if chapter < 16:
            if row[columns["instance_set_next"]] != str(3010001 + chapter) or \
                    row[columns["front_instance"]] != str(3110000010 + chapter * 1000):
                raise ValueError("Unexpected chapter route graph: " + identity)
        elif row[columns["instance_set_next"]] not in ("", "0") or \
                row[columns["front_instance"]] not in ("", "0"):
            raise ValueError("Unexpected final chapter route graph")

    return _patch_rows(text, CHAPTER_IDS, fields, ("instance_set_enter_level",), update)


def patch_bundle(raw: bytes) -> bytes:
    """Patch config/clientexel/instance.ab; update the APK index afterwards."""
    return _patch(raw, "Instance", patch_instance_text)


def patch_instance_bundle(raw: bytes) -> bytes:
    """Explicit alias for callers handling both campaign tables."""
    return patch_bundle(raw)


def patch_instance_set_bundle(raw: bytes) -> bytes:
    """Patch config/clientexel/instanceset.ab; update the APK index afterwards."""
    return _patch(raw, "InstanceSet", patch_instance_set_text)
