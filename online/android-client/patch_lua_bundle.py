"""Retarget the three author-injected Lua private-file paths for a new package."""

import UnityPy

OLD = 'com.codex.witchweapon.local'
NEW = 'com.codex.witchweapon.online.test'
CANDIDATE = 'com.codex.witchweapon.online.originalui.test'


def patch(raw, package=NEW):
    if package not in (NEW, CANDIDATE):
        raise ValueError('Unsupported isolated online test package')
    bundle = UnityPy.load(raw)
    found = 0
    for obj in bundle.objects:
        if obj.type.name != 'TextAsset':
            continue
        tree = obj.read_typetree()
        if tree['m_Name'] != 'init.lua':
            continue
        script = tree['m_Script']
        was_bytes = isinstance(script, bytes)
        if was_bytes:
            script = script.decode('utf-8')
        found = script.count(OLD)
        if found != 3:
            raise ValueError('Expected exactly three author-injected private-file paths')
        script = script.replace(OLD, package)
        tree['m_Script'] = script.encode('utf-8') if was_bytes else script
        obj.save_typetree(tree)
    if found != 3:
        raise ValueError('init.lua was not found')
    output = bundle.file.save(packer='original')
    check = UnityPy.load(output)
    for obj in check.objects:
        if obj.type.name != 'TextAsset':
            continue
        tree = obj.read_typetree()
        if tree['m_Name'] == 'init.lua':
            text = tree['m_Script']
            if isinstance(text, bytes):
                text = text.decode('utf-8')
            if text.count(package) != 3 or OLD in text:
                raise ValueError('Lua path patch did not round-trip')
            return output
    raise ValueError('Patched init.lua was not readable')
