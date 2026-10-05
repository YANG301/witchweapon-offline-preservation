"""Rebuild the isolated PC maze candidate with JDK8's bundled ASM."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import zipfile

PROJECT = Path(r"D:\Project\魔女兵器在线版")
AREA = PROJECT / "验收/迷宫修复"
PC = Path(r"D:\Project\魔女兵器工程恢复\本地模式服务\程序\witchweapon-legacy.jar")
ONLINE = AREA / "witchweapon-maze-candidate.jar"
JSON_JAR = Path(r"D:\Environment\Java\libraries\android-json-9.0.0_r61\android-json.jar")
JAVA = Path(r"D:\Environment\Java\jdk8\bin")

def main():
    assert hashlib.sha256(PC.read_bytes()).hexdigest() == "c1f4fda847f48bf80a5d93361ede9241419f3f1e3c5ff3ca2addc7098cb7b427", "PC baseline changed; inspect before transplant"
    assert hashlib.sha256(ONLINE.read_bytes()).hexdigest() == "5b19a60a933e788c0fc9a24f6c2eaf6c60fa6b3e846c4c1d5c40cb3f01b0e7b8", "Online candidate must be frozen validated version"
    tool_classes = AREA / "PC工具类"
    tool_classes.mkdir(exist_ok=True)
    env = dict(os.environ, TEMP=r"D:\Environment\Java\temp", TMP=r"D:\Environment\Java\temp")
    subprocess.run([str(JAVA / "javac.exe"), "-XDignore.symbol.file", "-J-Dfile.encoding=UTF-8", "-encoding", "UTF-8", "-d", str(tool_classes), str(PROJECT / "tools/MazePcCandidatePatcher.java")], check=True, env=env)
    candidate = AREA / "本地模式候选/witchweapon-legacy.jar"
    cp = ";".join(map(str, (tool_classes, ONLINE, PC, JSON_JAR)))
    subprocess.run([str(JAVA / "java.exe"), "-Dfile.encoding=UTF-8", r"-Djava.io.tmpdir=D:\Environment\Java\temp", "-cp", cp, "MazePcCandidatePatcher", str(PC), str(ONLINE), str(candidate)], check=True, env=env)
    with zipfile.ZipFile(PC) as before, zipfile.ZipFile(candidate) as after:
        changed = [n for n in after.namelist() if n not in before.namelist() or before.read(n) != after.read(n)]
        assert set(changed) == {"com/codex/witchweapon/LocalSave.class", "com/codex/witchweapon/StandaloneServer.class", "com/codex/witchweapon/BarrierLabyrinth.class", "com/codex/witchweapon/BarrierLabyrinth$Group.class", "com/codex/witchweapon/MazeRules.class", "maze_rules.json"}
    report = {"candidate": str(candidate), "candidateSha256": hashlib.sha256(candidate.read_bytes()).hexdigest(), "changedMembers": changed, "pcCurrentFilesModified": False}
    (AREA / "本地模式候选成员核对.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))

if __name__ == "__main__":
    main()
