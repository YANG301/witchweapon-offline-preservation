"""Move the author APK's Unity bootstrap endpoint to the isolated test port."""

import UnityPy

OLD = 'http://127.0.0.1:19876'
NEW = 'http://127.0.0.1:19877'
CANDIDATE = 'http://127.0.0.1:19878'
EXPECTED = 20


def patch(raw, endpoint=NEW):
    if endpoint not in (NEW, CANDIDATE):
        raise ValueError('Unsupported isolated loopback endpoint')
    bundle = UnityPy.load(raw)
    changed = 0
    for obj in bundle.objects:
        if obj.type.name != 'MonoBehaviour':
            continue
        tree = obj.read_typetree()
        if tree.get('m_Name') != 'accConf' or 'bytes' not in tree:
            continue
        decoded = bytes(value ^ 255 for value in tree['bytes']).decode('utf-8-sig')
        changed = decoded.count(OLD)
        if changed != EXPECTED:
            raise ValueError('Unexpected original bootstrap endpoint count')
        decoded = decoded.replace(OLD, endpoint)
        tree['bytes'] = list(bytes(value ^ 255 for value in ('\ufeff' + decoded).encode('utf-8')))
        obj.save_typetree(tree)
    if changed != EXPECTED:
        raise ValueError('Original accConf object not found')
    output = bundle.file.save(packer='original')
    verify = UnityPy.load(output)
    for obj in verify.objects:
        if obj.type.name != 'MonoBehaviour':
            continue
        tree = obj.read_typetree()
        if tree.get('m_Name') == 'accConf':
            decoded = bytes(value ^ 255 for value in tree['bytes']).decode('utf-8-sig')
            if decoded.count(endpoint) == EXPECTED and OLD not in decoded:
                return output
    raise ValueError('Patched accConf did not round-trip')
