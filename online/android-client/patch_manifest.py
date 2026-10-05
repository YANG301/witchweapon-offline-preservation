"""Patch the preserved binary AndroidManifest without recompiling game resources.

The original Unity Activity keeps its SDK intent and Unity metadata. A new
native login Activity becomes the only MAIN/LAUNCHER entry point.
"""

import struct

NONE = 0xFFFFFFFF
START = 0x0102
END = 0x0103
GAME = 'com.shuiqinling.ww.android.LingGameActivity'
LOGIN = 'com.codex.witchweapon.OnlineLoginActivity'
ANDROID = 'http://schemas.android.com/apk/res/android'


def u32(data, offset):
    return struct.unpack_from('<I', data, offset)[0]


def split_chunks(raw):
    if struct.unpack_from('<HHI', raw) != (3, 8, len(raw)):
        raise ValueError('Unexpected AndroidManifest header')
    chunks = []
    offset = 8
    while offset < len(raw):
        kind, header, size = struct.unpack_from('<HHI', raw, offset)
        if size < header or size < 8 or offset + size > len(raw):
            raise ValueError('Invalid AndroidManifest chunk')
        chunks.append(bytearray(raw[offset:offset + size]))
        offset += size
    return chunks


def string_pool(pool):
    if struct.unpack_from('<H', pool)[0] != 1:
        raise ValueError('Missing string pool')
    count, style_count, flags, strings_start, styles_start = struct.unpack_from('<5I', pool, 8)

    def length8(at):
        value = pool[at]
        return (((value & 127) << 8) | pool[at + 1], at + 2) if value & 128 else (value, at + 1)

    def length16(at):
        value = struct.unpack_from('<H', pool, at)[0]
        return (((value & 32767) << 16) | struct.unpack_from('<H', pool, at + 2)[0], at + 4) if value & 32768 else (value, at + 2)

    result = []
    for index in range(count):
        at = strings_start + u32(pool, 28 + index * 4)
        if flags & 256:
            _, at = length8(at)
            size, at = length8(at)
            result.append(bytes(pool[at:at + size]).decode('utf-8'))
        else:
            size, at = length16(at)
            result.append(bytes(pool[at:at + size * 2]).decode('utf-16le'))
    return result, (style_count, flags, styles_start)


def start_tag(chunk, strings):
    if struct.unpack_from('<H', chunk)[0] != START:
        return None
    return strings[u32(chunk, 20)]


def end_tag(chunk, strings):
    if struct.unpack_from('<H', chunk)[0] != END:
        return None
    return strings[u32(chunk, 20)]


def attributes(chunk, strings):
    attr_start, attr_size, count = struct.unpack_from('<HHH', chunk, 24)
    if attr_size != 20:
        raise ValueError('Unexpected AXML attribute size')
    offset = 16 + attr_start
    return {strings[u32(chunk, offset + index * 20 + 4)]: offset + index * 20
            for index in range(count)}


def attribute_value(chunk, at, strings):
    raw = u32(chunk, at + 8)
    if raw != NONE:
        return strings[raw]
    if chunk[at + 15] == 3:
        return strings[u32(chunk, at + 16)]
    return None


def assign_string(chunk, at, value, strings):
    if value not in strings:
        strings.append(value)
    index = strings.index(value)
    struct.pack_into('<I', chunk, at + 8, index)
    struct.pack_into('<HBBI', chunk, at + 12, 8, 0, 3, index)


def add_exported_true(chunk, strings):
    """Give the new launcher an explicit Android 12-compatible exported flag."""
    attrs = attributes(chunk, strings)
    if 'exported' in attrs:
        raise ValueError('Unexpected existing exported attribute')
    # The original aapt pool already maps `exported` to android.R.attr.exported.
    if 'exported' not in strings or ANDROID not in strings:
        raise ValueError('Required Android attribute strings missing')
    attr_start, attr_size, count = struct.unpack_from('<HHH', chunk, 24)
    offset = 16 + attr_start
    # The existing attributes are in resource-ID order: label, name, then
    # launchMode. Insert exported immediately after name (0x01010010).
    insert_at = attrs['name'] + attr_size
    if insert_at < offset or insert_at > offset + count * attr_size:
        raise ValueError('Invalid attribute insertion offset')
    record = struct.pack('<IIIHBBI', strings.index(ANDROID),
                         strings.index('exported'), NONE, 8, 0, 0x12, 1)
    chunk[insert_at:insert_at] = record
    struct.pack_into('<H', chunk, 28, count + 1)
    struct.pack_into('<I', chunk, 4, len(chunk))


def paired_end(chunks, index, strings):
    if start_tag(chunks[index], strings) is None:
        raise ValueError('Expected start tag')
    depth = 0
    for cursor in range(index, len(chunks)):
        if start_tag(chunks[cursor], strings) is not None:
            depth += 1
        elif end_tag(chunks[cursor], strings) is not None:
            depth -= 1
            if depth == 0:
                return cursor
    raise ValueError('Unterminated manifest element')


def direct_children(block, strings):
    result = []
    index = 1
    while index < len(block) - 1:
        if start_tag(block[index], strings) is None:
            raise ValueError('Unexpected node in Activity')
        end = paired_end(block, index, strings)
        result.append(block[index:end + 1])
        index = end + 1
    return result


def filter_intent(block, strings, login):
    kept = [block[0]]
    for child in direct_children(block, strings):
        tag = start_tag(child[0], strings)
        at = attributes(child[0], strings).get('name')
        value = attribute_value(child[0], at, strings) if at is not None else ''
        if login:
            if tag == 'action' and value != 'android.intent.action.MAIN':
                continue
            if tag == 'category' and value not in {
                    'android.intent.category.LAUNCHER',
                    'android.intent.category.LEANBACK_LAUNCHER'}:
                continue
        else:
            if tag == 'action' and value == 'android.intent.action.MAIN':
                continue
            if tag == 'category' and value in {
                    'android.intent.category.LAUNCHER',
                    'android.intent.category.LEANBACK_LAUNCHER'}:
                continue
        kept.extend(child)
    kept.append(block[-1])
    return kept


def serialize_pool(original, strings, info):
    style_count, flags, styles_start = info
    original_count = u32(original, 8)
    offsets = []
    encoded = bytearray()

    def enc8(value):
        return bytes([(value >> 8) | 128, value & 255]) if value >= 128 else bytes([value])

    def enc16(value):
        return struct.pack('<HH', (value >> 16) | 32768, value & 65535) if value >= 32768 else struct.pack('<H', value)

    for text in strings:
        offsets.append(len(encoded))
        units = len(text.encode('utf-16le')) // 2
        if flags & 256:
            raw = text.encode('utf-8')
            encoded += enc8(units) + enc8(len(raw)) + raw + b'\0'
        else:
            encoded += enc16(units) + text.encode('utf-16le') + b'\0\0'
    encoded += b'\0' * (-len(encoded) % 4)
    style_offsets = bytes(original[28 + original_count * 4:28 + (original_count + style_count) * 4])
    styles = bytes(original[styles_start:]) if styles_start else b''
    strings_start = 28 + (len(strings) + style_count) * 4
    new_styles_start = strings_start + len(encoded) if styles else 0
    size = strings_start + len(encoded) + len(styles)
    header = struct.pack('<HHI5I', 1, 28, size, len(strings), style_count,
                         flags & ~1, strings_start, new_styles_start)
    return header + struct.pack('<' + 'I' * len(offsets), *offsets) + style_offsets + encoded + styles


def patch(raw, package='com.codex.witchweapon.online.test'):
    chunks = split_chunks(raw)
    strings, pool_info = string_pool(chunks[0])
    activity_at = None
    for index, chunk in enumerate(chunks):
        if start_tag(chunk, strings) != 'activity':
            continue
        attrs = attributes(chunk, strings)
        if attribute_value(chunk, attrs['name'], strings) == GAME:
            if activity_at is not None:
                raise ValueError('Duplicate Unity Activity')
            activity_at = index
    if activity_at is None:
        raise ValueError('Unity Activity not found')
    activity_end = paired_end(chunks, activity_at, strings)
    game_block = chunks[activity_at:activity_end + 1]
    children = direct_children(game_block, strings)
    filters = [child for child in children if start_tag(child[0], strings) == 'intent-filter']
    if len(filters) != 1:
        raise ValueError('Expected one original Unity intent-filter')
    original_filter = filters[0]
    game_children = []
    for child in children:
        game_children.extend(filter_intent(child, strings, False) if child is original_filter else child)
    game_result = [game_block[0], *game_children, game_block[-1]]
    login_start = bytearray(game_block[0])
    login_attrs = attributes(login_start, strings)
    assign_string(login_start, login_attrs['name'], LOGIN, strings)
    if 'label' in login_attrs:
        assign_string(login_start, login_attrs['label'], '魔女兵器·在线测试', strings)
    add_exported_true(login_start, strings)
    login_result = [login_start, *filter_intent(original_filter, strings, True), game_block[-1]]

    output = []
    index = 1
    while index < len(chunks):
        if index == activity_at:
            output.extend(game_result)
            output.extend(login_result)
            index = activity_end + 1
            continue
        chunk = chunks[index]
        tag = start_tag(chunk, strings)
        if tag == 'manifest':
            assign_string(chunk, attributes(chunk, strings)['package'], package, strings)
        elif tag == 'application':
            attrs = attributes(chunk, strings)
            if 'label' in attrs:
                assign_string(chunk, attrs['label'], '魔女兵器·在线测试', strings)
        output.append(chunk)
        index += 1
    pool = serialize_pool(chunks[0], strings, pool_info)
    body = pool + b''.join(bytes(chunk) for chunk in output)
    result = struct.pack('<HHI', 3, 8, len(body) + 8) + body
    # Reparse before returning. Exactly one launcher Activity must remain.
    verify = split_chunks(result)
    verify_strings, _ = string_pool(verify[0])
    names = [attribute_value(chunk, attributes(chunk, verify_strings)['name'], verify_strings)
             for chunk in verify if start_tag(chunk, verify_strings) == 'activity']
    if names.count(GAME) != 1 or names.count(LOGIN) != 1:
        raise ValueError('Patched Activity declarations are inconsistent')
    return result
