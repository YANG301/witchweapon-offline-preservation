"""Build the follow-up initial CSC group/four-slot fix without changing frozen jars."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import zipfile
from build_maze_candidate import strip_unpublished

PROJECT = Path(r"D:\Project\魔女兵器在线版")
AREA = PROJECT / "验收/迷宫修复"
BASELINE = AREA / "witchweapon-maze-candidate.jar"
PC_BASELINE = AREA / "本地模式候选/witchweapon-legacy.jar"
JAVA = Path(r"D:\Environment\Java\jdk8\bin")
JSON_JAR = Path(r"D:\Environment\Java\libraries\android-json-9.0.0_r61\android-json.jar")
ENV = dict(os.environ, TEMP=r"D:\Environment\Java\temp", TMP=r"D:\Environment\Java\temp")

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    assert sha(BASELINE) == "5b19a60a933e788c0fc9a24f6c2eaf6c60fa6b3e846c4c1d5c40cb3f01b0e7b8"
    assert sha(PC_BASELINE) == "1a82a775014402780a5d3537cf8f7bbb925bc36623c50d8fd382dca3c579e1f7"
    sources = AREA / "选组候选源码/com/codex/witchweapon"
    sources.mkdir(parents=True, exist_ok=True)
    classes = AREA / "选组候选类"
    classes.mkdir(exist_ok=True)
    for name in ("BarrierLabyrinth", "LocalSave"):
        code = (PROJECT / f"legacy-server/src/com/codex/witchweapon/{name}.java").read_text(encoding="utf-8")
        if name == "LocalSave":
            code = strip_unpublished(code)
        (sources / f"{name}.java").write_text(code, encoding="utf-8")
    subprocess.run([str(JAVA / "javac.exe"), "-J-Dfile.encoding=UTF-8", "-encoding", "UTF-8", "-source", "8", "-target", "8", "-cp", f"{BASELINE};{JSON_JAR}", "-d", str(classes)] + [str(f) for f in sources.glob("*.java")], check=True, env=ENV)
    patches = {str(f.relative_to(classes)).replace("\\", "/"): f.read_bytes() for f in classes.rglob("*.class")}
    online = AREA / "witchweapon-maze-group-candidate.jar"
    with zipfile.ZipFile(BASELINE) as old, zipfile.ZipFile(online, "w") as new:
        for e in old.infolist():
            new.writestr(e, patches.pop(e.filename, old.read(e)))
        assert not patches
    tool_classes = AREA / "选组PC工具类"
    tool_classes.mkdir(exist_ok=True)
    subprocess.run([str(JAVA / "javac.exe"), "-XDignore.symbol.file", "-J-Dfile.encoding=UTF-8", "-encoding", "UTF-8", "-d", str(tool_classes), str(PROJECT / "tools/MazePcCandidatePatcher.java")], check=True, env=ENV)
    pc = AREA / "本地模式选择上限候选/witchweapon-legacy.jar"
    cp = ";".join(map(str, (tool_classes, online, PC_BASELINE, JSON_JAR)))
    subprocess.run([str(JAVA / "java.exe"), "-Dfile.encoding=UTF-8", r"-Djava.io.tmpdir=D:\Environment\Java\temp", "-cp", cp, "MazePcCandidatePatcher", str(PC_BASELINE), str(online), str(pc), "cscNormalCommit"], check=True, env=ENV)
    reports = []
    for before, after in ((BASELINE, online), (PC_BASELINE, pc)):
        with zipfile.ZipFile(before) as old, zipfile.ZipFile(after) as new:
            changed = [n for n in new.namelist() if old.read(n) != new.read(n)]
            assert set(changed) <= {"com/codex/witchweapon/BarrierLabyrinth.class", "com/codex/witchweapon/BarrierLabyrinth$Group.class", "com/codex/witchweapon/LocalSave.class"}
            assert old.read("com/codex/witchweapon/StandaloneServer.class") == new.read("com/codex/witchweapon/StandaloneServer.class")
            assert old.read("maze_rules.json") == new.read("maze_rules.json")
        reports.append({"baseline": str(before), "baselineSha256": sha(before), "candidate": str(after), "candidateSha256": sha(after), "changedMembers": changed})
    (AREA / "初次选组候选成员核对.json").write_text(json.dumps(reports, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(reports, ensure_ascii=False))

if __name__ == "__main__":
    main()
