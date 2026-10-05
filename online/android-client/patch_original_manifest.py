"""Keep the original Unity login Activity as the isolated candidate launcher."""

import struct

import patch_manifest as axml


PACKAGE = 'com.codex.witchweapon.online.originalui.test'
LABEL = '魔女兵器·原版登录测试'


def patch(raw):
    chunks = axml.split_chunks(raw)
    strings, pool_info = axml.string_pool(chunks[0])
    game = []
    for index, chunk in enumerate(chunks):
        tag = axml.start_tag(chunk, strings)
        if tag == 'manifest':
            axml.assign_string(chunk, axml.attributes(chunk, strings)['package'], PACKAGE, strings)
        elif tag == 'application':
            attrs = axml.attributes(chunk, strings)
            if 'label' not in attrs or axml.attribute_value(chunk, attrs['name'], strings) \
                    != 'com.codex.witchweapon.OfflineApplication':
                raise ValueError('Unexpected original Application declaration')
            axml.assign_string(chunk, attrs['label'], LABEL, strings)
        elif tag == 'activity':
            attrs = axml.attributes(chunk, strings)
            if axml.attribute_value(chunk, attrs['name'], strings) == axml.GAME:
                game.append(index)
                if 'label' in attrs:
                    axml.assign_string(chunk, attrs['label'], LABEL, strings)
                axml.add_exported_true(chunk, strings)
    if len(game) != 1:
        raise ValueError('Expected exactly one original Unity Activity')
    block = chunks[game[0]:axml.paired_end(chunks, game[0], strings) + 1]
    filters = [child for child in axml.direct_children(block, strings)
               if axml.start_tag(child[0], strings) == 'intent-filter']
    if len(filters) != 1:
        raise ValueError('Expected exactly one original Unity launcher intent-filter')
    actions = set()
    for child in axml.direct_children(filters[0], strings):
        attrs = axml.attributes(child[0], strings)
        if 'name' in attrs:
            actions.add(axml.attribute_value(child[0], attrs['name'], strings))
    if not {'android.intent.action.MAIN', 'android.intent.category.LAUNCHER'} <= actions:
        raise ValueError('Original Unity launcher intent changed')
    pool = axml.serialize_pool(chunks[0], strings, pool_info)
    body = pool + b''.join(bytes(chunk) for chunk in chunks[1:])
    result = struct.pack('<HHI', 3, 8, len(body) + 8) + body
    verify = axml.split_chunks(result)
    verify_strings, _ = axml.string_pool(verify[0])
    declared = [axml.attribute_value(chunk, axml.attributes(chunk, verify_strings)['name'], verify_strings)
                for chunk in verify if axml.start_tag(chunk, verify_strings) == 'activity']
    if declared.count(axml.GAME) != 1 or axml.LOGIN in declared:
        raise ValueError('Candidate manifest did not preserve the original-only launcher')
    return result
