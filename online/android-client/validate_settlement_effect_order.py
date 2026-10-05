"""Validate Lua with the recovered ToLua runtime and an isolated draw-call model."""
import ctypes
from pathlib import Path

SOURCE = Path(__file__).resolve().parent / 'lua' / 'init-settlement-effect-order.lua'
DLL = Path(r'D:\Project\魔女兵器工程恢复\原版\Unity恢复\ExportedProject\Assets\Plugins\x86_64\tolua.dll')

MODEL = r'''
package.preload['tolua.reflection'] = function() return {} end
local id = 0
function object(values)
    values = values or {}; id = id + 1; values.id = id
    function values:Equals(other) return self == other end
    function values:GetInstanceID() return self.id end
    return values
end
function array(values)
    local result = {Length = #values, Count = #values}
    for i, value in ipairs(values) do result[i - 1] = value end
    return result
end
local assemblies = {}
typeof = function(name)
    if name == 'UnityEngine.ParticleSystemRenderer' then
        if not assemblies['UnityEngine.ParticleSystemModule'] then return nil end
    elseif name:find('UnityEngine.', 1, true) == 1 then
        if not assemblies['UnityEngine.CoreModule'] then return nil end
    end
    return name
end
tolua = {loadassembly = function(name) assemblies[name] = true end}
tolua.getfield = function(_, name)
    return {Get = function(_, value) return value[name] end}
end
tolua.getproperty = function(_, name)
    return {
        Get = function(_, value) return value[name] end,
        Set = function(_, value, replacement) value[name] = replacement end
    }
end
tolua.getmethod = function(_, name)
    assert(name == 'GetComponentsInChildren')
    return {Call = function(_, value, typeName, includeInactive)
        assert(includeInactive == true); return value[typeName]
    end}
end
LateUpdateBeat = {Add = function(self, callback) self.callback = callback end}
logs = {}
UnityEngine = {
    Time = {realtimeSinceStartup = 1},
    Debug = {
        Log = function(message) logs[#logs + 1] = message end,
        LogError = function(message) error(message) end
    },
    Object = {FindObjectOfType = function() return scene end}
}
uiMaterial = object({renderQueue = 3120})
mesh = object({sortingLayerID = 140, sortingOrder = 2})
draw = object({dynamicMaterial = uiMaterial, mRenderer = mesh})
widget = object({drawCall = draw})
particleMaterial = object({renderQueue = 3047})
particle = object({sortingLayerID = 0, sortingOrder = 9,
    sharedMaterials = array({particleMaterial})})
exp = object({gameObject = object({UIWidget = array({widget})})})
effect = object({gameObject = object({
    ['UnityEngine.ParticleSystemRenderer'] = array({particle})})})
card = object({expBar = exp, levelUpAnim = effect})
scene = object({gameObject = object({activeInHierarchy = true}),
    servantPhotoList = array({card})})
'''

CHECKS = r'''
assert(LateUpdateBeat.callback ~= nil)
LateUpdateBeat.callback()
assert(particleMaterial.renderQueue == 3119, 'Particle must use live queue, not a prefab constant')
assert(particle.sortingLayerID == 140 and particle.sortingOrder == 2,
    'A runtime particle sorting override must not place it above the UI')
assert(uiMaterial.renderQueue == 3120 and mesh.sortingOrder == 2,
    'UI draw calls must remain untouched')
uiMaterial.renderQueue = 3140
UnityEngine.Time.realtimeSinceStartup = 1.1
LateUpdateBeat.callback()
assert(particleMaterial.renderQueue == 3139, 'NGUI material rebuild must be followed')
scene.gameObject.activeInHierarchy = false
UnityEngine.Time.realtimeSinceStartup = 2
LateUpdateBeat.callback()
assert(particleMaterial.renderQueue == 3047, 'Shared material must be restored on exit')
assert(particle.sortingLayerID == 0 and particle.sortingOrder == 9,
    'Renderer settings must be restored on exit')
draw.dynamicMaterial = nil
scene.gameObject.activeInHierarchy = true
UnityEngine.Time.realtimeSinceStartup = 3
LateUpdateBeat.callback()
assert(particleMaterial.renderQueue == 3047, 'Wait for a real UI draw call')
draw.dynamicMaterial = uiMaterial
UnityEngine.Time.realtimeSinceStartup = 3.1
LateUpdateBeat.callback()
assert(particleMaterial.renderQueue == 3139, 'Repeated settlement entry must bind again')
assert(logs[1] == 'ONLINE_SETTLEMENT_EFFECT_ORDER_READY 53')
assert(logs[2]:find('before=3047 after=3119', 1, true))
'''

def main():
    dll = ctypes.CDLL(str(DLL))
    dll.luaL_newstate.restype = ctypes.c_void_p
    dll.luaL_openlibs.argtypes = [ctypes.c_void_p]
    dll.luaL_loadbuffer.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_size_t, ctypes.c_char_p]
    dll.luaL_loadbuffer.restype = ctypes.c_int
    dll.lua_pcall.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int]
    dll.lua_pcall.restype = ctypes.c_int
    dll.lua_tolstring.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p]
    dll.lua_tolstring.restype = ctypes.c_char_p
    dll.lua_close.argtypes = [ctypes.c_void_p]
    state = dll.luaL_newstate()
    if not state:
        raise MemoryError('Lua state creation failed')
    try:
        dll.luaL_openlibs(state)
        code = (MODEL + '\n' + SOURCE.read_text(encoding='utf-8') + '\n' + CHECKS).encode('utf-8')
        result = dll.luaL_loadbuffer(state, code, len(code), b'settlement-order-check')
        if result == 0:
            result = dll.lua_pcall(state, 0, 0, 0)
        if result != 0:
            raise AssertionError(dll.lua_tolstring(state, -1, None).decode('utf-8', errors='replace'))
        print('SETTLEMENT_ORDER_CHECKS_PASSED live_queue sorting restore reentry delayed_draw_call')
    finally:
        dll.lua_close(state)

if __name__ == '__main__':
    main()
