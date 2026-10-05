"""Extract the original shared quest_type=6 story tasks from achievement.txt."""

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
    tasks = []
    with args.source.open("r", encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            if row.get("channel_group") != "0" or row.get("quest_type") != "6":
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
            tasks.append({
                "id": number(row["ID"]),
                "questType": 6,
                "type": row["achievement_type"],
                "front": number(row["front_achievement"]),
                "next": number(row["next_achievement"]),
                "arg1": number(row["achievement_argu1"]),
                "arg2": number(row["achievement_argu2"]),
                "arg3": number(row["achievement_argu3"]),
                "rewards": rewards,
            })
    ids = {task["id"] for task in tasks}
    counts = {kind: sum(task["type"] == kind for task in tasks)
              for kind in ("001", "012", "013", "021", "023", "060")}
    expected = {"001": 10, "012": 7, "013": 5, "021": 73, "023": 4, "060": 7}
    if len(tasks) != 106 or len(ids) != 106 or counts != expected:
        raise ValueError(f"Unexpected shared original story task table: {counts}")
    for task in tasks:
        if task["front"] and task["front"] not in ids:
            raise ValueError(f"Missing story predecessor for {task['id']}")
        if task["next"] and task["next"] not in ids:
            raise ValueError(f"Missing story successor for {task['id']}")
    document = {
        "schemaVersion": 1,
        "sourceSha256": hashlib.sha256(raw).hexdigest(),
        "counts": counts,
        "tasks": tasks,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(document, ensure_ascii=False,
                                      separators=(",", ":")) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
