"""从现有服务只读生成独立活动影子源文件；不编译、不启动服务、不联网。"""
from __future__ import annotations
import csv
import hashlib
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

OUT = Path(__file__).resolve().parent
LAB = OUT.parent
PROJECT = LAB.parent
SOURCE = PROJECT / "legacy-server/src/com/codex/witchweapon"
RECOVERY = PROJECT.parent / "魔女兵器工程恢复"
PACKAGE = OUT / "com/codex/witchweapon"
CATALOG = LAB / "activity_catalog.json"
JAR = RECOVERY / "本地模式服务/程序/witchweapon-legacy.jar"
GUIDES = RECOVERY / "原版/可读脚本与配置/配置/clientexel/lessontrigger.txt"

def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def write(path: Path, text: str) -> None:
    if not path.resolve().is_relative_to(OUT):
        raise ValueError("输出越过独立服务源码目录")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
    if path.read_text(encoding="utf-8") != text:
        raise ValueError(f"UTF-8回读不一致: {path}")

def replace_once(text: str, old: str, new: str) -> str:
    if text.count(old) != 1:
        raise ValueError(f"影子补丁定位不唯一: {old[:100]!r}")
    return text.replace(old, new, 1)

def prepare() -> dict:
    data = json.loads(CATALOG.read_text(encoding="utf-8"))
    assert data["mode"] == "local-activity-lab" and data["event"]["id"] == 5
    assert sorted(map(int, data["stages"])) == list(range(3190001001,3190001026))
    if not JAR.is_file():
        raise FileNotFoundError(JAR)
    sources = [SOURCE / x for x in ("LocalSave.java","StandaloneServer.java","CaphActivityAccess.java")]
    before = {str(path):digest(path) for path in [*sources, CATALOG, JAR, GUIDES]}
    rows = list(csv.DictReader(GUIDES.open(encoding="utf-8-sig", newline="")))
    ids = sorted({int(row["recID"]) for row in rows if row["recID"].isdigit()
                  and row.get("channel_group") in {"0","25"} and 0 < int(row["recID"]) <= 99999})
    helper = PACKAGE / "LocalActivityLab.java"
    text = helper.read_text(encoding="utf-8")
    if "/* LAB_GUIDE_IDS */" in text:
        text = replace_once(text, "/* LAB_GUIDE_IDS */", ",".join(map(str, ids)))
        write(helper,text)
    else:
        # Re-running is deterministic; never duplicate the guide array.
        expected = "private static final int[] GUIDE_IDS={"+",".join(map(str,ids))+"};"
        if expected not in text:
            raise ValueError("引导ID与已有影子代码不一致")
    guide_jobs = sorted({int(row[key]) for row in rows for key in ("quest1","quest2","quest3")
                         if row.get("channel_group") in {"0","25"} and row.get(key,"").isdigit()
                         and int(row[key]) > 0})
    if "/* LAB_GUIDE_TASKS */" in text:
        text = replace_once(text,"/* LAB_GUIDE_TASKS */",",".join(str(value)+"L" for value in guide_jobs))
        write(helper,text)
    elif "private static final long[] GUIDE_TASKS={"+",".join(str(value)+"L" for value in guide_jobs)+"};" not in text:
        raise ValueError("教程任务ID与已有影子代码不一致")

    text = sources[0].read_text(encoding="utf-8")
    text = replace_once(text,
        "    }\n    private void commit(JSONObject next) throws Exception {",
        "        JSONObject labSeed=new JSONObject(state.toString());\n"
        "        if(LocalActivityLab.initialize(labSeed,null,System.currentTimeMillis()/1000))commit(labSeed);\n"
        "    }\n    private void commit(JSONObject next) throws Exception {")
    text = replace_once(text,
        "        if(catalog!=null)staminaCatalog=catalog;\n        JSONObject refreshed=new JSONObject(state.toString());",
        "        if(catalog!=null)staminaCatalog=catalog;\n"
        "        JSONObject labSeed=new JSONObject(state.toString());\n"
        "        if(LocalActivityLab.initialize(labSeed,catalog,now))commit(labSeed);\n"
        "        JSONObject refreshed=new JSONObject(state.toString());")
    text = replace_once(text,
        '        if(path.startsWith("/game/"))path=path.substring(5);\n',
        '        if(path.startsWith("/game/"))path=path.substring(5);\n'
        '        if(LocalActivityLab.intercept(path,args)){\n'
        '            JSONObject labNext=new JSONObject(state.toString());\n'
        '            LocalActivityLab.Action labAction=LocalActivityLab.respond(labNext,catalog,path,args,seed,storyFixture,now);\n'
        '            if(labAction.changed)commit(labNext);\n'
        '            return labAction.response;\n'
        '        }\n')
    text = replace_once(text,
        '        String[] fields={"version","name","gold","rmb","stamina","activityStamina",',
        '        String[] fields={"version","name","gold","rmb","stamina","activityStamina",\n'
        '            "storyCurrency","activityStoryCurrency",')
    text = replace_once(text,
        '            "active","activeStage","battleMazeRound","startKey"};',
        '            "active","activeStage","battleMazeRound","startKey","labActivity"};')
    text = replace_once(text,
        '            r.set(128,state.optLong("storyCurrency",r.number(128,0)));',
        '            r.set(128,state.optLong("storyCurrency",r.number(128,0)));\n'
        '            r.set(129,state.optLong("activityStoryCurrency",r.number(129,0)));')
    write(PACKAGE / "LocalSave.java",text)

    text = sources[1].read_text(encoding="utf-8")
    text = replace_once(text,"        PreservedBattleCatalog.install(responses);",
        "        PreservedBattleCatalog.install(responses);\n"
        "        LocalActivityLab.install(responses);\n"
        "        LocalActivityLab.configureRoleCatalog(responses.getJSONObject(\"_catalog\"));\n"
        "        routes.addAll(LocalActivityLab.routes());")
    text = replace_once(text,
        "            synchronized (save) {\n            JSONObject response = responseFixture(responses,path);",
        "            synchronized (save) {\n"
        "            if(LocalActivityLab.direct(path)){\n"
        "                String labPath=LocalActivityLab.normalize(path);\n"
        "                JSONObject template=responseFixture(responses,labPath.equals(\"/ap/getRoleInfo\")\n"
        "                    ?\"/combat/role/info\":\"/ap/instance/get\");\n"
        "                byte[] seed=labPath.equals(\"/ap/getRoleInfo\") || labPath.equals(\"/ap/instance/get\") || labPath.equals(\"/ap/getInfo\")\n"
        "                    ?com.codex.witchweapon.host.Base64.decode(template.getString(\"base64\"),0):new byte[0];\n"
        "                byte[] result=save.respond(path,args,seed,responses.optJSONObject(\"_catalog\"),null,stages,dailyBattles,weaponFurnace);\n"
        "                return new Reply(200,\"application/octet-stream\",result);\n"
        "            }\n"
        "            JSONObject response = responseFixture(responses,path);")
    text = replace_once(text,
        "                         !PreservedBattleCatalog.contains(requested))",
        "                         !PreservedBattleCatalog.contains(requested) && !LocalActivityLab.contains(requested))")
    text = replace_once(text,
        "        catch (LocalSave.AdminMissing ex) { reply = error(404,\"game_save_not_found\"); }",
        "        catch (LocalActivityLab.Rejected ex) {\n"
        "            System.err.println(\"LOCAL_ACTIVITY_REJECT \"+ex.code);\n"
        "            reply=error(422,\"local_activity_\"+ex.code.toLowerCase(java.util.Locale.ROOT));\n"
        "        }\n"
        "        catch (LocalSave.AdminMissing ex) { reply = error(404,\"game_save_not_found\"); }")
    write(PACKAGE / "StandaloneServer.java",text)

    text = sources[2].read_text(encoding="utf-8")
    text = replace_once(text,"static final long SERIAL=1;","static final long SERIAL=5;")
    text = replace_once(text,"static final long TIME_ID=1030001;","static final long TIME_ID=1030005;")
    text = replace_once(text,"        return false;","        return now>=LocalActivityLab.OPEN_START && now<LocalActivityLab.OPEN_END;")
    text = replace_once(text,".set(1,0).set(2,SERIAL).set(12,0)",".set(1,1).set(2,SERIAL).set(12,1)")
    text = replace_once(text,"        putTime(times,TIME_ID,0,0);",
        "        putTime(times,TIME_ID,LocalActivityLab.OPEN_START,LocalActivityLab.OPEN_END);")
    # Rewrite stale preservation comments so this shadow source describes its real behavior.
    text = text.replace("/** Original activity and explicitly scheduled star-shop product clocks. */",
                        "/** Independent lab clock; ID5 is open only in this shadow jar. */")
    text = "\n".join(line for line in text.split("\n") if not line.lstrip().startswith("//"))
    write(PACKAGE / "CaphActivityAccess.java",text)

    write(OUT / "resources/activity_catalog.json",CATALOG.read_text(encoding="utf-8"))
    for path in [*sources,CATALOG,JAR,GUIDES]:
        assert digest(path)==before[str(path)], f"只读输入发生变化: {path}"
    manifest = {
        "mode":"local-activity-lab","schemaVersion":1,
        "baseJar":str(JAR),"readOnlyInputs":before,"guideIds":ids,
        "compileSources":[str(PACKAGE / x) for x in ("LocalActivityLab.java","LocalSave.java","StandaloneServer.java","CaphActivityAccess.java")],
        "resourceRoot":str(OUT / "resources"),"originalStageCount":25,"routesPerFloor":4,
        "fullOriginalServerAlgorithm":False,"verification":"生成与UTF-8/源hash一致性检查；未编译、未联网、未实机测试"
    }
    write(OUT / "服务生成清单.json",json.dumps(manifest,ensure_ascii=False,indent=2)+"\n")
    return manifest

if __name__ == "__main__":
    manifest=prepare()
    print(json.dumps({"mode":manifest["mode"],"compileSources":manifest["compileSources"],
                      "resourceRoot":manifest["resourceRoot"],"guideCount":len(manifest["guideIds"]),
                      "originalStageCount":25,"compiled":False,"networkUsed":False},ensure_ascii=False,indent=2))
