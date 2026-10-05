"""Change only the compiled resource package name for the separate test APK."""

import struct

OLD = 'com.codex.witchweapon.local'
NEW = 'com.codex.witchweapon.online.test'
CANDIDATE = 'com.codex.witchweapon.online.originalui.test'


def patch(raw, package=NEW):
    if package not in (NEW, CANDIDATE):
        raise ValueError('Unsupported isolated online test package')
    output = bytearray(raw)
    position = struct.unpack_from('<H', output, 2)[0]
    replaced = 0
    while position < len(output):
        kind, header, size = struct.unpack_from('<HHI', output, position)
        if size < header or position + size > len(output):
            raise ValueError('Invalid resource table chunk')
        if kind == 0x0200:
            name = bytes(output[position + 12:position + 268]).decode('utf-16le').split('\0', 1)[0]
            if name != OLD:
                raise ValueError('Unexpected resource table package name: ' + name)
            output[position + 12:position + 268] = package.encode('utf-16le').ljust(256, b'\0')
            replaced += 1
        position += size
    if replaced != 1:
        raise ValueError('Expected one compiled resource package')
    return bytes(output)
