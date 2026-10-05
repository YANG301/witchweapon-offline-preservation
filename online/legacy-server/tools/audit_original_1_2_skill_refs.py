"""Audit starter active-skill references without changing a combat fixture.

Original templates survive alongside the author's Offline_ variants, but
timing/target selection changed. The original server-supplied active-skill
parameters are missing, so this emits candidates for later client testing,
never a replacement combat payload.
"""
from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
RECOVERY = Path(r"D:\Project\魔女兵器工程恢复")
ORIGINAL = RECOVERY / "原版/可读脚本与配置/配置/xmlconf/skill/spells.xml"
OFFLINE = RECOVERY / "单机版/可读脚本与配置/配置/xmlconf/skill/spells.xml"
RESPONSES = ROOT / "resources/offline_responses.json"
OUTPUT = ROOT / "test-profiles/original-1-2/skill-reference-audit.json"
ORIGINAL_SHA256 = "d9bf4c9728a4b832c4d58c2fe7ffc7f0d83a8e71272ead07d2ebb6bcd72deae8"
OFFLINE_SHA256 = "5402ab59fc5e3e51da420ba7f5ec1322797ce67f024f9cba422e5ba45d6329d5"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def points(node: ET.Element) -> list[dict[str, str]]:
    return [{"delay": item.get("Delay", ""), "repeat": item.get("RepeatNum", "")}
            for item in node if item.get("PointType") == "OnEffectPoint"]


def build() -> dict:
    if digest(ORIGINAL) != ORIGINAL_SHA256 or digest(OFFLINE) != OFFLINE_SHA256:
        raise ValueError("Skill XML changed; re-audit before comparing role references")
    original = {entry.get("TempletID"): entry for entry in ET.parse(ORIGINAL).getroot()}
    offline = {entry.get("TempletID"): entry for entry in ET.parse(OFFLINE).getroot()}
    responses = json.loads(RESPONSES.read_text(encoding="utf-8"))
    role = base64.b64decode(responses["/combat/role/info"]["base64"], validate=True)
    refs = []
    for unit in range(100, 104):
        orig_name = f"Servant{unit}_ActiveSkill_01"
        offline_name = f"Offline_{orig_name}"
        if orig_name not in original or offline_name not in offline:
            raise ValueError("Missing role skill template " + orig_name)
        if role.count(offline_name.encode("ascii")) != 1:
            raise ValueError("Unexpected live role fixture reference count for " + offline_name)
        if ET.tostring(original[orig_name]) != ET.tostring(offline[orig_name]):
            raise ValueError("The offline APK changed the preserved original template " + orig_name)
        old_points = points(original[orig_name])
        new_points = points(offline[offline_name])
        if old_points == new_points:
            raise ValueError("Expected an author timeline change in " + offline_name)
        refs.append({"unit": unit, "liveReference": offline_name,
                     "originalCandidate": orig_name,
                     "originalTemplateStillPresent": True,
                     "originalEffectPoints": old_points,
                     "authorEffectPoints": new_points,
                     "safeAutomaticReplacement": False})
    return {"schemaVersion": 1, "testOnly": True,
            "originalSpellXmlSha256": ORIGINAL_SHA256,
            "offlineSpellXmlSha256": OFFLINE_SHA256,
            "roleFixtureSha256": digest(RESPONSES),
            "scope": "starter units 100-103; not a recovered original server skill configuration",
            "reasonReplacementBlocked": "Original server parameters/timing are missing; author variants alter effect-point scheduling and unit 100 targeting.",
            "references": refs}


def main() -> None:
    audit = build()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if json.loads(OUTPUT.read_text(encoding="utf-8")) != audit:
        raise AssertionError("Skill audit UTF-8 round-trip failed")
    print(json.dumps({"status": "ORIGINAL_ROLE_SKILL_AUDIT_OK", "units": len(audit["references"]),
                      "automaticReplacement": False, "outputSha256": digest(OUTPUT)},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
