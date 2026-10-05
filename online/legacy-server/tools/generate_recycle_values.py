"""Extract only evidence-backed recycling values from the preserved Item table."""
import csv
import hashlib
import json
from pathlib import Path

SOURCE = Path(r"D:\Project\魔女兵器工程恢复\原版\可读脚本与配置\配置\clientexel\item.txt")
RESPONSES = Path(__file__).resolve().parents[1] / "resources/offline_responses.json"
DEST = Path(__file__).resolve().parents[1] / "resources/recycle_values.json"

source = SOURCE.read_bytes()
catalog = json.loads(RESPONSES.read_text(encoding="utf-8"))["_catalog"]["items"]
rows = list(csv.DictReader(source.decode("utf-8-sig").splitlines()))[2:]
values = {}
for row in rows:
    item_id = row["ID"].strip()
    raw_value = row["recycle_value"].strip()
    if not item_id.isdecimal() or not raw_value:
        continue
    value = int(raw_value)
    if value < 0:
        raise ValueError(f"negative recycle value: {item_id}")
    if value > 0:
        if item_id not in catalog:
            raise ValueError(f"recyclable item absent from inventory catalog: {item_id}")
        if item_id in values:
            raise ValueError(f"duplicate recyclable item: {item_id}")
        values[item_id] = value

payload = {
    "schemaVersion": 1,
    "source": str(SOURCE),
    "sourceSha256": hashlib.sha256(source).hexdigest(),
    "values": dict(sorted(values.items(), key=lambda pair: int(pair[0]))),
}
DEST.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(f"{len(values)} recyclable item values -> {DEST}")
