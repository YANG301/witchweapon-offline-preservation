"""Extract the original CN mainline/achievement task rows from achievement.txt."""
import argparse
import csv
import hashlib
import json
from pathlib import Path


def number(value):
    return int(value) if value else 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    raw = args.source.read_bytes()
    rows = []
    with args.source.open("r", encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            if row.get("channel_group") != "25" or row.get("quest_type") not in ("1", "5"):
                continue
            rewards = []
            for slot in range(1, 6):
                kind = number(row[f"attachment_type{slot}"])
                if kind:
                    rewards.append({
                        "type": kind,
                        "id": number(row[f"attachment_id{slot}"]),
                        "value": number(row[f"attachment_value{slot}"]),
                        "count": number(row[f"attachment_num{slot}"]),
                    })
            rows.append({
                "id": number(row["ID"]),
                "questType": number(row["quest_type"]),
                "type": row["achievement_type"],
                "front": number(row["front_achievement"]),
                "next": number(row["next_achievement"]),
                "arg1": number(row["achievement_argu1"]),
                "arg2": number(row["achievement_argu2"]),
                "arg3": number(row["achievement_argu3"]),
                "rewards": rewards,
            })
    counts = {kind: sum(row["questType"] == kind for row in rows) for kind in (1, 5)}
    if counts != {1: 50, 5: 42} or len({row["id"] for row in rows}) != 92:
        raise ValueError(f"Unexpected original CN task table: {counts}")
    document = {
        "schemaVersion": 1,
        "sourceSha256": hashlib.sha256(raw).hexdigest(),
        "counts": {"achievement": 50, "mainline": 42},
        "tasks": rows,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(document, ensure_ascii=False, separators=(",", ":")) + "\n",
                           encoding="utf-8")


if __name__ == "__main__":
    main()
