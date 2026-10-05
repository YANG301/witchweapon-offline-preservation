'use strict';

// Read-only Java input trace for an x86_64 emulator running translated ARM64 IL2CPP.
// It never records coordinates, account data, input text, or raw MotionEvent objects.
const counts = {
  unityDispatchDown: 0,
  unityDispatchMove: 0,
  unityDispatchUp: 0,
  unityInjectDown: 0,
  unityInjectMove: 0,
  unityInjectUp: 0,
};
let hooked = [];
const arch = Process.arch;
const armLibListed = Process.enumerateModules().some((m) => m.name === 'libil2cpp.so');

function countEvent(kind, input) {
  if (input === null || input === undefined) return;
  let action;
  try { action = input.getActionMasked(); } catch (_) { return; }
  if (action === 0) counts[kind + 'Down']++;
  else if (action === 1 || action === 3) counts[kind + 'Up']++;
  else if (action === 2) counts[kind + 'Move']++;
}

Java.perform(() => {
  let unity;
  try { unity = Java.use('com.unity3d.player.UnityPlayer'); }
  catch (error) {
    console.log(JSON.stringify({tag: 'WW-UNITY-JAVA-INPUT', arch, armLibListed,
      error: 'UnityPlayer class unavailable', hooksInstalled: 0}));
    return;
  }
  for (const [methodName, kind] of [
    ['dispatchTouchEvent', 'unityDispatch'],
    ['injectEvent', 'unityInject'],
  ]) {
    let method;
    try { method = unity[methodName]; } catch (_) { continue; }
    if (!method || !method.overloads) continue;
    for (const overload of method.overloads) {
      if (overload.argumentTypes.length !== 1) continue;
      overload.implementation = function (event) {
        countEvent(kind, event);
        return overload.call(this, event);
      };
      hooked.push(methodName);
    }
  }
  console.log(JSON.stringify({tag: 'WW-UNITY-JAVA-INPUT', arch, armLibListed,
    hooksInstalled: hooked.length, methods: hooked}));
});

setInterval(() => console.log(JSON.stringify({tag: 'WW-UNITY-JAVA-INPUT',
  arch, armLibListed, hooksInstalled: hooked.length, counts})), 2000);
