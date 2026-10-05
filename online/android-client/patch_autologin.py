"""Seed the original client's placeholder cache after native online auth.

Apply this to the lua.ab bytes returned by patch_lua_bundle.patch(). The Java
adapter must create MARKER_FILE only after HTTPS auth and the authenticated
legacy-state mirror succeed, and remove it on Application start/session expiry.
No Go Bearer, password or user email is ever copied into the Unity account cache.
The original server/zone selection and Enter Game button remain manual.
Optional future work: after a runtime-proven successful token login, a one-shot
UpdateBeat could wait for active RoleLoginView and non-null currUserZone, then
invoke its private OnClickEnterGameBtn through tolua reflection. This has not
been tested and is deliberately not part of the current patch.
"""

from pathlib import Path
import argparse
import hashlib
import json
import zipfile

import UnityPy


MARKER_FILE = "/data/data/com.codex.witchweapon.online.test/files/online_bootstrap_ready"
MARKER_VALUE = "online-v1\n"
PACKAGE = "com.codex.witchweapon.online.test"
PLACEHOLDER_ACCOUNT = "online-placeholder@example.invalid"
PLACEHOLDER_TOKEN = "offline-local"
BEGIN = "-- BEGIN CODEX ONLINE PLACEHOLDER AUTOLOGIN"
END = "-- END CODEX ONLINE PLACEHOLDER AUTOLOGIN"
TRIGGER = "VideoManager.ClosePVToLoginFormal()"


def _as_text(script):
    return script.decode("utf-8") if isinstance(script, bytes) else script


def _restore_type(text, old):
    return text.encode("utf-8") if isinstance(old, bytes) else text


def lua_block():
    # LuaMethod.Call expects only the LuaMethod object for a static method,
    # and the object plus all declared arguments for an instance method.
    # SetLastLoginAccCache has four System.String arguments, so use the typed
    # gettypemethod overload; the untyped overload cannot accept those args.
    return """-- BEGIN CODEX ONLINE PLACEHOLDER AUTOLOGIN
do
    local marker = io.open('/data/data/com.codex.witchweapon.online.test/files/online_bootstrap_ready', 'rb')
    local allowed = marker and marker:read('*a') == 'online-v1\\n'
    if marker then marker:close() end
    if allowed then
        local ok, err = pcall(function()
            require 'tolua.reflection'
            tolua.loadassembly('Assembly-CSharp')
            local kind = typeof('WaterBell.ProjX.Data.Local.UserAccCacheMngr')
            local flags = 65535
            local manager = tolua.gettypemethod(kind, 'GetInstance', flags):Call()
            local stringType = typeof('System.String')
            local setLast = tolua.gettypemethod(kind, 'SetLastLoginAccCache', flags,
                System.Type.DefaultBinder,
                {stringType, stringType, stringType, stringType}, nil)
            setLast:Call(manager, 'online-placeholder@example.invalid', 'offline-local', '2', '')
            tolua.gettypemethod(kind, 'AddLastLoginAccCache', flags):Call(manager)
        end)
        if not ok then UnityEngine.Debug.LogError('ONLINE_LOCAL_CACHE ' .. tostring(err)) end
    end
end
-- END CODEX ONLINE PLACEHOLDER AUTOLOGIN
"""


def patch(raw):
    """Return a new bundle with only init.lua changed; fail on drift/reapply."""
    bundle = UnityPy.load(raw)
    baseline = {}
    changed = 0
    for obj in bundle.objects:
        if obj.type.name != "TextAsset":
            continue
        tree = obj.read_typetree()
        script = tree["m_Script"]
        baseline[obj.path_id] = _as_text(script)
        if tree["m_Name"] != "init.lua":
            continue
        changed += 1
        text = _as_text(script)
        if text.count(TRIGGER) != 1 or BEGIN in text or END in text:
            raise ValueError("Expected exactly one unpatched Unity login trigger")
        if text.count(PACKAGE) != 3 or "com.codex.witchweapon.local" in text:
            raise ValueError("Apply patch_lua_bundle before this patch")
        patched = text.replace(TRIGGER, lua_block() + TRIGGER, 1)
        tree["m_Script"] = _restore_type(patched, script)
        obj.save_typetree(tree)
    if changed != 1:
        raise ValueError("Expected exactly one init.lua TextAsset")
    output = bundle.file.save(packer="original")
    reopened = UnityPy.load(output)
    after = {}
    init_count = 0
    for obj in reopened.objects:
        if obj.type.name != "TextAsset":
            continue
        tree = obj.read_typetree()
        text = _as_text(tree["m_Script"])
        after[obj.path_id] = text
        if tree["m_Name"] == "init.lua":
            init_count += 1
            if (text.count(BEGIN) != 1 or text.count(END) != 1
                    or text.count(TRIGGER) != 1 or text.count(MARKER_FILE) != 1
                    or text.count(PLACEHOLDER_TOKEN) != 1):
                raise ValueError("Auto-login Lua did not survive bundle round trip")
    if init_count != 1 or set(after) != set(baseline):
        raise ValueError("Bundle TextAsset set changed unexpectedly")
    for path_id, old in baseline.items():
        if BEGIN not in after[path_id] and after[path_id] != old:
            raise ValueError("Unrelated TextAsset changed")
    return output


def check():
    """Read-only unit check against the pinned offline APK and recovered ABI."""
    import build_online_apk
    import patch_lua_bundle

    source = build_online_apk.SOURCE
    if build_online_apk.sha256(source) != build_online_apk.SOURCE_SHA:
        raise ValueError("Offline source APK hash changed")
    with zipfile.ZipFile(source) as archive:
        for abi in ("arm64-v8a", "armeabi-v7a"):
            if archive.getinfo("lib/" + abi + "/libil2cpp.so").file_size < 1_000_000:
                raise ValueError("Missing IL2CPP ABI: " + abi)
        metadata = archive.read("assets/bin/Data/Managed/Metadata/global-metadata.dat")
        for method in (b"UserAccCacheMngr", b"GetInstance",
                       b"SetLastLoginAccCache", b"AddLastLoginAccCache",
                       b"AccountTokenLogin"):
            if method not in metadata:
                raise ValueError("Missing IL2CPP metadata method: " + repr(method))
        source_bundle = archive.read("assets/assetbundle/lua/lua.ab")
        original_index = archive.read("assets/m.assets_list.txt")

    # This recovered code documents the precise Lua reflection invocation:
    # static Call receives no object; instance Call receives the object and
    # the Type[]-declared argument count.
    root = Path(r"D:\Project\魔女兵器工程恢复\原版\Unity恢复\ExportedProject\Assets\Scripts\Assembly-CSharp")
    lua_method = (root / "LuaInterface/LuaMethod.cs").read_text(encoding="utf-8-sig")
    cache = (root / "WaterBell/ProjX/Data/Local/UserAccCacheMngr.cs").read_text(encoding="utf-8-sig")
    for proof in ("if (!method.IsStatic)", "ToLua.CheckArgsCount(L, list.Count + offset)"):
        if proof not in lua_method:
            raise ValueError("Lua reflection call contract changed: " + proof)
    for proof in ("UserAccCacheMngr GetInstance()", "SetLastLoginAccCache(string userName, string token, string type, string nickName", "void AddLastLoginAccCache()"):
        if proof not in cache:
            raise ValueError("Original cache API changed: " + proof)

    base = patch_lua_bundle.patch(source_bundle)
    result = patch(base)
    index = build_online_apk.patch_index(original_index, {"/lua/lua.ab": result})
    digest = hashlib.md5(result).hexdigest()
    entry = (digest + "=/lua/lua.ab:" + str(len(result))).encode("ascii")
    if index.count(entry) != 1:
        raise ValueError("Updated m.assets_list.txt does not match Lua bundle")
    return {"status": "AUTOLOGIN_STATIC_CHECK_OK", "bundleBytes": len(result),
            "bundleMd5": digest, "indexUpdated": True,
            "markerContract": MARKER_FILE,
            "apkBuildRequired": True, "runtimeValidated": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", required=True)
    parser.parse_args()
    print(json.dumps(check(), ensure_ascii=False))
