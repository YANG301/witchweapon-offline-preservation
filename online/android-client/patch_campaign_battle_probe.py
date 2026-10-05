"""Append a rate-limited, read-only campaign/guide diagnostic to init.lua."""

import hashlib

import UnityPy

MARKER = "-- BEGIN CODEX CAMPAIGN BATTLE PROBE"
BLOCK = r'''
-- BEGIN CODEX CAMPAIGN BATTLE PROBE
do
    local setupOk = pcall(function()
        require 'tolua.reflection'
        tolua.loadassembly('Assembly-CSharp')
        tolua.loadassembly('Assembly-CSharp-firstpass')
        local F, fields, properties = 65535, {}, {}
        local nextPoll, lastLog, previous = 0, -10, ''
        local runtimeErrorLogged = false
        local function field(t, n, o)
            local ok, value = pcall(function()
                local key = t .. ':' .. n
                if fields[key] == nil then fields[key] = tolua.getfield(typeof(t), n, F) or false end
                if fields[key] then return fields[key]:Get(o) end
            end)
            if not ok then return nil end
            return value
        end
        local function prop(t, n, o)
            local ok, value = pcall(function()
                local key = t .. ':' .. n
                if properties[key] == nil then properties[key] = tolua.getproperty(typeof(t), n, F) or false end
                if properties[key] then return properties[key]:Get(o, {}) end
            end)
            if not ok then return nil end
            return value
        end
        local function safe(f)
            local ok, value = pcall(f)
            return ok and tostring(value) or 'error'
        end
        local function alive(o)
            if o == nil then return false end
            local ok, missing = pcall(function() return o:Equals(nil) end)
            return not ok or not missing
        end
        local function typename(o)
            return safe(function() return o:GetType().Name end)
        end
        local function pos(o)
            return safe(function()
                local p = o.transform.position
                return string.format('%.2f,%.2f,%.2f', p.x, p.y, p.z)
            end)
        end
        local function active(o)
            if not alive(o) then return 'absent' end
            return safe(function()
                local g = o.gameObject or o
                return tostring(g.activeSelf) .. '/' .. tostring(g.activeInHierarchy)
            end)
        end
        local function graphState(tree)
            if not alive(tree) then return 'absent' end
            local gt = 'NodeCanvas.GuideLessonTrees.GuideLessonTree'
            local node = prop(gt, 'currentNode', tree)
            local parts = {
                'name=' .. safe(function() return tree.name end),
                'rec=' .. tostring(field(gt, 'recID', tree)),
                'running=' .. tostring(prop('NodeCanvas.Framework.Graph', 'isRunning', tree)),
                'paused=' .. tostring(prop('NodeCanvas.Framework.Graph', 'isPaused', tree)),
                'node=' .. (node and typename(node) or 'absent'),
                'nodeID=' .. tostring(node and prop('NodeCanvas.Framework.Node', 'ID', node)),
                'nodeStatus=' .. tostring(node and prop('NodeCanvas.Framework.Node', 'status', node))
            }
            if node then
                local round = field('NodeCanvas.GuideLessonTrees.GuideRoundNode', '_roundInfo', node)
                if round then
                    local rt = 'NodeCanvas.GuideLessonTrees.GuideRound'
                    for _, n in ipairs({'execState', 'currentActionIndex', 'isA4CMDRunning'}) do
                        parts[#parts + 1] = n .. '=' .. tostring(field(rt, n, round))
                    end
                    for _, n in ipairs({'_b4cmdActionList', '_a4cmdActionList'}) do
                        local list = field(rt, n, round)
                        local lt = 'NodeCanvas.Framework.GuideTaskList'
                        local index = list and field(lt, 'currentActionIndex', list)
                        local actions = list and field(lt, 'actions', list)
                        parts[#parts + 1] = n .. '=' .. tostring(index) .. ':' .. safe(function()
                            if actions and index and index >= 0 and index < actions.Count then
                                return typename(actions[index])
                            end
                            return 'none'
                        end)
                    end
                end
            end
            return table.concat(parts, ',')
        end
        local function snapshot()
            local parts = {'timeScale=' .. tostring(UnityEngine.Time.timeScale),
                'demi=' .. tostring(prop('PausePool', 'DemiPaused', nil)),
                'skill=' .. tostring(prop('PausePool', 'SkillPaused', nil)),
                'floor=' .. tostring(field('WaterBell.ProjX.GlobalVariable', 'floor_height', nil))}
            local gt = 'NodeCanvas.GuideLessonTrees.GuideLessonTree'
            parts[#parts + 1] = 'dialogue={' .. graphState(prop(gt, 'currentDialogue', nil)) .. '}'
            parts[#parts + 1] = 'executor={' .. graphState(field(
                'WaterBell.ProjX.Guide.GuideLessonExecutor', 'CurrentLessonTree', nil)) .. '}'
            local stage = field('WaterBell.ProjX.Guide.Content.Stage', '_instance', nil)
            parts[#parts + 1] = 'stage=' .. active(stage)
            local pic = stage and field('WaterBell.ProjX.Guide.Content.Stage', 'picTextLayer', stage)
            parts[#parts + 1] = 'pic=' .. active(pic)
            if pic then
                local pt = 'WaterBell.ProjX.Guide.Content.PicTextLayer'
                parts[#parts + 1] = 'picNext=' .. tostring(prop(pt, 'isNext', pic))
                for _, n in ipairs({'label', 'spriteBG', 'spriteArrow', 'button', 'buttonClose', 'trsPosition'}) do
                    local item = field(pt, n, pic)
                    parts[#parts + 1] = n .. '=' .. active(item) .. '@' .. (item and pos(item) or 'none')
                    if n == 'label' or n == 'spriteBG' then
                        parts[#parts + 1] = n .. 'Alpha=' .. safe(function() return item.alpha end)
                    end
                end
                local cursor = pic.transform
                local ancestry = {}
                for i = 1, 5 do
                    if not alive(cursor) then break end
                    ancestry[#ancestry + 1] = active(cursor)
                    cursor = cursor.parent
                end
                parts[#parts + 1] = 'picParents=' .. table.concat(ancestry, '>')
            end
            local hero = field('HeroEntity', 'instance', nil)
            parts[#parts + 1] = 'hero=' .. active(hero) .. '@' .. (hero and pos(hero) or 'none')
            local pool = field('EntityPool', '_instance', nil)
            local entities = pool and field('EntityPool', 'sourceList', pool)
            local count, samples = 0, {}
            if entities then
                for i = 0, math.min(entities.Count, 256) - 1 do
                    local entity = entities[i]
                    if alive(entity) and entity ~= hero then
                        count = count + 1
                        if #samples < 12 then samples[#samples + 1] = typename(entity) .. ':' .. active(entity) .. '@' .. pos(entity) end
                    end
                end
            end
            parts[#parts + 1] = 'otherEntities=' .. count .. '[' .. table.concat(samples, ';') .. ']'
            local center = field('ButtonExRegCenter', '_instance', nil)
            local registry = center and field('ButtonExRegCenter', 'id2objMap', center)
            for i = 1, 3 do
                local key = 'battleui_skillslots:' .. i
                parts[#parts + 1] = 'slot' .. i .. '=' .. safe(function()
                    if registry and registry:ContainsKey(key) then
                        local button = registry:get_Item(key)
                        return active(button) .. '@' .. pos(button)
                    end
                    return 'unregistered'
                end)
            end
            return table.concat(parts, ' ')
        end
        UpdateBeat:Add(function()
            local now = UnityEngine.Time.realtimeSinceStartup
            if now < nextPoll then return end
            nextPoll = now + 1
            local ok, value = pcall(snapshot)
            if not ok then
                if not runtimeErrorLogged then UnityEngine.Debug.Log('WW-CAMPAIGN-PROBE read-error'); runtimeErrorLogged = true end
                return
            end
            if (value ~= previous and now - lastLog >= 2) or now - lastLog >= 5 then
                UnityEngine.Debug.Log('WW-CAMPAIGN-PROBE ' .. value)
                previous, lastLog = value, now
            end
        end)
    end)
    if not setupOk then pcall(function() UnityEngine.Debug.Log('WW-CAMPAIGN-PROBE setup-error') end) end
end
-- END CODEX CAMPAIGN BATTLE PROBE
'''


def _text(value):
    return value.decode("utf-8") if isinstance(value, bytes) else value


def patch(script: str) -> str:
    """Append only; preserve every byte of the caller's existing Lua text."""
    if not isinstance(script, str):
        raise TypeError("Expected init.lua string")
    if MARKER in script or "UpdateBeat:Add(function()" not in script:
        raise ValueError("Unexpected or already patched init.lua")
    return script + BLOCK


def patch_bundle(raw: bytes) -> bytes:
    bundle = UnityPy.load(raw)
    before, original, changed = {}, None, 0
    for obj in bundle.objects:
        if obj.type.name != "TextAsset":
            continue
        tree = obj.read_typetree()
        script = tree["m_Script"]
        text = _text(script)
        before[obj.path_id] = hashlib.sha256(text.encode("utf-8")).digest()
        if tree["m_Name"] == "init.lua":
            if MARKER in text or "UpdateBeat:Add(function()" not in text:
                raise ValueError("Unexpected or already patched init.lua")
            original = text
            replacement = patch(text)
            tree["m_Script"] = replacement.encode("utf-8") if isinstance(script, bytes) else replacement
            obj.save_typetree(tree)
            changed += 1
    if changed != 1:
        raise ValueError("Expected one init.lua")
    output = bundle.file.save(packer="original")
    found = 0
    for obj in UnityPy.load(output).objects:
        if obj.type.name != "TextAsset":
            continue
        tree = obj.read_typetree()
        text = _text(tree["m_Script"])
        if tree["m_Name"] == "init.lua":
            if text != original + BLOCK or text.count(MARKER) != 1:
                raise ValueError("Probe round-trip changed existing init.lua")
            found += 1
        elif hashlib.sha256(text.encode("utf-8")).digest() != before[obj.path_id]:
            raise ValueError("Unrelated Lua asset changed")
    if found != 1:
        raise ValueError("Probe missing after round-trip")
    return output
