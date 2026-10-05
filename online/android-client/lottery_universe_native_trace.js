'use strict';

// Read-only Frida probe for the original arm64 IL2CPP game binary.
// Attach only to the isolated test emulator after libil2cpp.so is loaded.
// It logs aggregate event counts and booleans; no account, text or coordinates.
if (Process.arch !== 'arm64') {
  console.log(JSON.stringify({
    tag: 'WW-LOTTERY-NATIVE',
    processArch: Process.arch,
    expectedIl2cppArch: 'arm64',
    hooksInstalled: false,
    reason: 'translated ARM64 IL2CPP cannot be hooked by host-architecture Interceptor',
  }));
  throw new Error('Native probe stopped before hooking: process/IL2CPP architectures differ');
}
const lib = Process.getModuleByName('libil2cpp.so');
const at = (rva) => lib.base.add(rva);
const active = Object.create(null);
const totals = {
  update: 0,
  mouseHeld: 0,
  mouseReleased: 0,
  raycasts: 0,
  raycastHits: 0,
  connected: 0,
  opened: 0,
  drawFinished: 0,
  camInteractionEnabled: 0,
  camInteractionDisabled: 0,
};
let lastSelf = null;
let lastSimulatedMouse = 'unread';
let lastSample = 0;
const getSimulateMouseWithTouches = new NativeFunction(
  at(0x2af3eec), 'int', []);

function safePointer(p) {
  return p && !p.isNull();
}

function readIntField(object, offset) {
  if (!safePointer(object)) return null;
  try { return object.add(offset).readS32(); } catch (_) { return null; }
}

function readBoolField(object, offset) {
  if (!safePointer(object)) return null;
  try { return object.add(offset).readU8() !== 0; } catch (_) { return null; }
}

function readPointerField(object, offset) {
  if (!safePointer(object)) return null;
  try { return object.add(offset).readPointer(); } catch (_) { return null; }
}

function snapshot() {
  const self = lastSelf;
  const stars = readPointerField(self, 0xe0);       // Star[]
  const connected = readPointerField(self, 0xc8);   // List<Star>
  return {
    tag: 'WW-LOTTERY-NATIVE',
    update: totals.update,
    mouseHeld: totals.mouseHeld,
    mouseReleased: totals.mouseReleased,
    raycasts: totals.raycasts,
    raycastHits: totals.raycastHits,
    connectedCalls: totals.connected,
    opened: totals.opened,
    drawFinished: totals.drawFinished,
    camInteractionEnabled: totals.camInteractionEnabled,
    camInteractionDisabled: totals.camInteractionDisabled,
    simulateMouseWithTouches: lastSimulatedMouse,
    starsLength: readIntField(stars, 0x18),
    connectedCount: readIntField(connected, 0x18),
    connectComplete: readBoolField(self, 0x120),
    bgCamPresent: safePointer(readPointerField(self, 0x88)),
  };
}

function withinUpdate() {
  return (active[Process.getCurrentThreadId()] || 0) > 0;
}

Interceptor.attach(at(0x3bd3ffc), {
  onEnter(args) {
    const tid = Process.getCurrentThreadId();
    active[tid] = (active[tid] || 0) + 1;
    lastSelf = args[0];
    totals.update++;
    const now = Date.now();
    if (now - lastSample >= 1000) {
      lastSample = now;
      try { lastSimulatedMouse = getSimulateMouseWithTouches() !== 0; }
      catch (_) { lastSimulatedMouse = 'read-error'; }
    }
  },
  onLeave() {
    const tid = Process.getCurrentThreadId();
    active[tid] = Math.max(0, (active[tid] || 1) - 1);
  },
});

Interceptor.attach(at(0x2af3b3c), { // Input.GetMouseButton(0)
  onLeave(retval) {
    if (withinUpdate() && (retval.toInt32() & 1)) totals.mouseHeld++;
  },
});
Interceptor.attach(at(0x2af3c0c), { // Input.GetMouseButtonUp(0)
  onLeave(retval) {
    if (withinUpdate() && (retval.toInt32() & 1)) totals.mouseReleased++;
  },
});
Interceptor.attach(at(0x379fed0), { // Physics.RaycastAll from this Update
  onLeave(retval) {
    if (!withinUpdate()) return;
    totals.raycasts++;
    const count = readIntField(retval, 0x18);
    if (count !== null && count > 0) totals.raycastHits += count;
  },
});
Interceptor.attach(at(0x3bd497c), { // LotteryUniverse.ConnectStar
  onEnter() { totals.connected++; },
});
Interceptor.attach(at(0x3bd52d4), { // LotteryUniverse.OpenPanel
  onEnter(args) { totals.opened++; lastSelf = args[0]; },
});
Interceptor.attach(at(0x3bd5238), { // SetCamInteractionState(bool)
  onEnter(args) {
    if (args[1].toInt32() & 1) totals.camInteractionEnabled++;
    else totals.camInteractionDisabled++;
  },
});
Interceptor.attach(at(0x3bd5804), { // LotteryUniverse.DrawFinishExecuted
  onEnter() { totals.drawFinished++; },
});

setInterval(() => console.log(JSON.stringify(snapshot())), 2000);
