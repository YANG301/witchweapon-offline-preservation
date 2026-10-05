package com.codex.witchweapon;

import android.app.Activity;
import android.util.Log;
import android.view.MotionEvent;
import android.view.Window;
import java.lang.reflect.InvocationHandler;
import java.lang.reflect.InvocationTargetException;
import java.lang.reflect.Method;
import java.lang.reflect.Proxy;

/** Test APK only: count touch phases without recording positions or UI text. */
final class LotteryTouchTrace implements InvocationHandler {
    private static final String TAG = "WW-LOTTERY-TOUCH";
    private final Window.Callback original;
    private int gesture;
    private int moves;

    private LotteryTouchTrace(Window.Callback original) {
        this.original = original;
    }

    static void attach(Activity activity) {
        Window window = activity.getWindow();
        Window.Callback current = window.getCallback();
        if (current == null) return;
        if (Proxy.isProxyClass(current.getClass()) &&
                Proxy.getInvocationHandler(current) instanceof LotteryTouchTrace) return;
        LotteryTouchTrace trace = new LotteryTouchTrace(current);
        Window.Callback replacement = (Window.Callback) Proxy.newProxyInstance(
                activity.getClassLoader(), new Class<?>[]{Window.Callback.class}, trace);
        window.setCallback(replacement);
        Log.i(TAG, "attached");
    }

    @Override public Object invoke(Object proxy, Method method, Object[] args) throws Throwable {
        MotionEvent touch = "dispatchTouchEvent".equals(method.getName()) &&
                args != null && args.length == 1 && args[0] instanceof MotionEvent
                ? (MotionEvent) args[0] : null;
        int action = touch == null ? -1 : touch.getActionMasked();
        if (action == MotionEvent.ACTION_DOWN) {
            gesture++;
            moves = 0;
            Log.i(TAG, "gesture=" + gesture + " phase=DOWN");
        } else if (action == MotionEvent.ACTION_MOVE) {
            moves++;
        }
        Object result;
        try {
            // Forward the exact original event. This probe never consumes or edits it.
            result = method.invoke(original, args);
        } catch (InvocationTargetException wrapped) {
            throw wrapped.getCause();
        }
        if (action == MotionEvent.ACTION_UP || action == MotionEvent.ACTION_CANCEL) {
            Log.i(TAG, "gesture=" + gesture + " phase=" +
                    (action == MotionEvent.ACTION_UP ? "UP" : "CANCEL") +
                    " moveCount=" + moves + " consumed=" + result);
        }
        return result;
    }
}
