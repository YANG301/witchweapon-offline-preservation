"""从用户提供的原始资源只读导出一段简体中文剧情；不修改 AB。"""
import argparse
import hashlib
import json
import re
from pathlib import Path

import UnityPy


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parents[1] / "data")
    args = parser.parse_args()
    original = args.source.read_bytes()
    candidates = []
    for obj in UnityPy.load(original).objects:
        if obj.type.name != "MonoBehaviour":
            continue
        tree = obj.read_typetree()
        if "bytes" not in tree:
            continue
        raw = bytes(tree["bytes"])
        payload = bytes(x ^ 0xFF for x in raw) if tree.get("isEncrypt") else raw
        candidates.append((tree, payload))
    if len(candidates) != 1:
        raise ValueError("预期恰好一个剧情载荷，实际为 %d" % len(candidates))
    tree, payload = candidates[0]
    lines = []
    for row in payload.decode("utf-8-sig").splitlines():
        columns = row.split("\t")
        if len(columns) < 3 or not columns[0].isdigit():
            raise ValueError("未知剧情表格格式")
        speaker = columns[1].split("@", 1)[-1]
        content = re.sub(r"\[(?:[0-9a-fA-F]{6}|-)\]", "", columns[2]).replace("\\n", "\n")
        lines.append({"speaker": speaker, "text": content})
    if not lines:
        raise ValueError("剧情为空")
    args.output.mkdir(parents=True, exist_ok=True)
    dataset = {"stories": [{"id": "opening-10001", "title": "序章·世界观试读", "lines": lines}]}
    (args.output / "stories.json").write_text(json.dumps(dataset, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    provenance = {
        "source": str(args.source.resolve()),
        "sourceSHA256": hashlib.sha256(original).hexdigest(),
        "decodedSHA256": hashlib.sha256(payload).hexdigest(),
        "isEncrypt": tree.get("isEncrypt"),
        "transformation": "Unity AB → MonoBehaviour.bytes → XOR 0xff（isEncrypt=1 时）→ UTF-8 → 简体中文第3列；去除旧NGUI颜色标签，展开换行",
        "storyId": "opening-10001", "lineCount": len(lines),
        "scope": "仅使用用户提供原始资源中实际存在的章节；未补造缺失剧情。"
    }
    (args.output / "provenance.json").write_text(json.dumps(provenance, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("已导出 %d 行剧情，UTF-8 JSON 已保存。" % len(lines))


if __name__ == "__main__":
    main()
