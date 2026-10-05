'use strict';

// Read-only, narrow Java probe for the isolated lottery test APK.
// Counts touch phases only; it does not record coordinates, text or account data.
Java.perform(function () {
  const counts = Object.create(null);
  const signature = ['android.view.MotionEvent'];

  function attachDeclared(className, label) {
    try {
      const type = Java.use(className);
      const declared = type.class.getDeclaredMethods();
      let ownsTouch = false;
      for (let i = 0; i < declared.length; i++) {
        if (String(declared[i].getName()) === 'onTouchEvent') {
          ownsTouch = true;
          break;
        }
      }
      if (!ownsTouch) {
        console.log('WW-LOTTERY-ROUTE ' + label + ' inherited; no hook installed');
        return;
      }
      const original = type.onTouchEvent.overload.apply(type.onTouchEvent, signature);
      counts[label] = { down: 0, move: 0, up: 0, cancel: 0, consumed: 0 };
      original.implementation = function (event) {
        const action = event.getActionMasked();
        const result = original.call(this, event);
        const counter = counts[label];
        if (action === 0) counter.down++;
        else if (action === 1) counter.up++;
        else if (action === 2) counter.move++;
        else if (action === 3) counter.cancel++;
        if (result) counter.consumed++;
        return result;
      };
      console.log('WW-LOTTERY-ROUTE ' + label + ' attached');
    } catch (error) {
      console.log('WW-LOTTERY-ROUTE ' + label + ' unavailable: ' + String(error));
    }
  }

  attachDeclared('com.unity3d.player.UnityPlayer', 'UnityPlayer.onTouchEvent');
  attachDeclared('com.shuiqinling.ww.android.UnityPlayerActivity',
                 'UnityPlayerActivity.onTouchEvent');
  attachDeclared('com.shuiqinling.ww.android.LingGameActivity',
                 'LingGameActivity.onTouchEvent');
  attachDeclared('android.view.SurfaceView', 'SurfaceView.onTouchEvent');

  setInterval(function () {
    console.log('WW-LOTTERY-ROUTE ' + JSON.stringify(counts));
  }, 5000);
});
