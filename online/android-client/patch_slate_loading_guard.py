"""Append the isolated slate hook to a hash-verified Lua bundle.

This tool builds an unsigned candidate only. It never edits a release manifest,
current pointer, Android package, save, device, or running server.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import UnityPy

MARKER = "ONLINE_SLATE_LOADING_GUARD_READY"


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def append_slate_loading_guard(raw: bytes, hook: str) -> tuple[bytes, dict]:
    if hook.count(MARKER) != 1:
        raise ValueError("Expected exactly one slate hook marker")
    env = UnityPy.load(raw)
    before = {obj.path_id: sha(obj.get_raw_data()) for obj in env.objects}
    candidates = [obj for obj in env.objects if obj.type.name == "TextAsset"
                  and obj.read_typetree().get("m_Name") == "init.lua"]
    if len(candidates) != 1:
        raise ValueError("Expected one init.lua TextAsset")
    target = candidates[0]
    tree = target.read_typetree()
    original_value = tree["m_Script"]
    original = original_value.decode("utf-8") if isinstance(original_value, bytes) else original_value
    if MARKER in original:
        raise ValueError("Slate guard is already present; refusing duplicate installation")
    proposed = original + "\n\n" + hook.rstrip("\n") + "\n"
    tree["m_Script"] = proposed.encode("utf-8") if isinstance(original_value, bytes) else proposed
    target.save_typetree(tree)
    output = env.file.save(packer="original")
    check = UnityPy.load(output)
    after = {obj.path_id: sha(obj.get_raw_data()) for obj in check.objects}
    if set(before) != set(after):
        raise ValueError("Unity object set changed")
    changed = [identity for identity in before if before[identity] != after[identity]]
    if changed != [target.path_id]:
        raise ValueError("An unrelated Unity object changed")
    found = next(obj.read_typetree()["m_Script"] for obj in check.objects
                 if obj.path_id == target.path_id)
    found_text = found.decode("utf-8") if isinstance(found, bytes) else found
    if found_text != proposed or not found_text.encode("utf-8").startswith(original.encode("utf-8")):
        raise ValueError("Original init.lua prefix was not retained byte-for-byte")
    qa = {"schemaVersion": 1, "inputSha256": sha(raw), "outputSha256": sha(output),
          "inputBytes": len(raw), "outputBytes": len(output),
          "originalInitSha256": sha(original.encode("utf-8")),
          "hookSha256": sha(hook.encode("utf-8")),
          "originalInitBytes": len(original.encode("utf-8")),
          "patchedInitBytes": len(proposed.encode("utf-8")),
          "unityObjects": len(before), "changedObjectIds": changed,
          "prefixPreserved": True, "unrelatedObjectsPreserved": True,
          "executionScope": "unsigned isolated candidate; no deployment"}
    return output, qa


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--hook", type=Path,
                        default=Path(__file__).resolve().parent / "lua/init-slate-loading-guard.lua")
    args = parser.parse_args()
    raw = args.source.read_bytes()
    if sha(raw) != args.expected_sha256:
        raise ValueError("Source bundle differs from the verified current baseline")
    hook = args.hook.read_text(encoding="utf-8-sig")
    output, qa = append_slate_loading_guard(raw, hook)
    args.destination.parent.mkdir(parents=True, exist_ok=True)
    if args.destination.exists() and args.destination.read_bytes() != output:
        raise FileExistsError("Refusing to replace a different candidate")
    args.destination.write_bytes(output)
    qa.update(sourcePath=str(args.source), candidatePath=str(args.destination), hookPath=str(args.hook))
    report = args.destination.with_suffix(args.destination.suffix + ".qa.json")
    report.write_text(json.dumps(qa, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"candidate": str(args.destination), "qa": str(report),
                      "sha256": qa["outputSha256"], "changedObjectIds": qa["changedObjectIds"],
                      "prefixPreserved": qa["prefixPreserved"]}, ensure_ascii=True))


if __name__ == "__main__":
    main()
