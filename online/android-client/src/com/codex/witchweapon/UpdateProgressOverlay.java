package com.codex.witchweapon;

import android.app.Activity;
import android.content.res.ColorStateList;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.ProgressBar;
import android.widget.TextView;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;

/** Small native progress layer over the original Unity resource-check scene. */
final class UpdateProgressOverlay {
    private static final int CYAN = Color.rgb(63, 209, 245);
    private final Activity activity;
    private final Handler ui = new Handler(Looper.getMainLooper());
    private final CountDownLatch hidden = new CountDownLatch(1);
    private View panel;
    private ProgressBar bar;
    private TextView status;
    private long shownAt;
    private long lastReportAt;
    private int lastPercent = -1;

    UpdateProgressOverlay(Activity activity) { this.activity = activity; }

    void begin() {
        if (activity == null) return;
        ui.post(new Runnable() {
            @Override public void run() {
                if (activity.isFinishing()) return;
                ViewGroup root = (ViewGroup) activity.findViewById(android.R.id.content);
                if (root == null) return;
                LinearLayout card = new LinearLayout(activity);
                card.setOrientation(LinearLayout.VERTICAL);
                card.setPadding(dp(16), dp(11), dp(16), dp(12));
                GradientDrawable background = new GradientDrawable();
                background.setColor(Color.argb(226, 10, 31, 52));
                background.setCornerRadius(dp(8));
                background.setStroke(dp(1), Color.argb(190, 63, 209, 245));
                card.setBackground(background);
                card.setElevation(dp(6));
                status = new TextView(activity);
                status.setGravity(Gravity.CENTER);
                status.setTextColor(Color.WHITE);
                status.setTypeface(Typeface.DEFAULT_BOLD);
                status.setTextSize(15);
                status.setText("正在检查游戏资源…");
                card.addView(status, new LinearLayout.LayoutParams(
                        ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));
                bar = new ProgressBar(activity, null, android.R.attr.progressBarStyleHorizontal);
                bar.setMax(100);
                bar.setIndeterminate(true);
                bar.setIndeterminateTintList(ColorStateList.valueOf(CYAN));
                bar.setProgressTintList(ColorStateList.valueOf(CYAN));
                bar.setProgressBackgroundTintList(ColorStateList.valueOf(0xFF31516A));
                LinearLayout.LayoutParams line = new LinearLayout.LayoutParams(
                        ViewGroup.LayoutParams.MATCH_PARENT, dp(7));
                line.topMargin = dp(9);
                card.addView(bar, line);
                FrameLayout.LayoutParams placement = new FrameLayout.LayoutParams(
                        ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT,
                        Gravity.BOTTOM | Gravity.CENTER_HORIZONTAL);
                placement.leftMargin = dp(48);
                placement.rightMargin = dp(48);
                placement.bottomMargin = dp(38);
                root.addView(card, placement);
                panel = card;
                shownAt = SystemClock.uptimeMillis();
            }
        });
    }

    void report(final String message) {
        if (activity == null) return;
        ui.post(new Runnable() {
            @Override public void run() {
                if (panel == null) return;
                status.setText(message);
                if (message.startsWith("正在校验")) bar.setIndeterminate(true);
                else if (message.startsWith("正在下载")) bar.setIndeterminate(false);
            }
        });
    }

    void transfer(long received, long total) {
        if (activity == null || total <= 0) return;
        final int percent = (int) Math.min(100L, received * 100L / total);
        long now = SystemClock.uptimeMillis();
        synchronized (this) {
            if (percent == lastPercent && now - lastReportAt < 150) return;
            lastPercent = percent;
            lastReportAt = now;
        }
        ui.post(new Runnable() {
            @Override public void run() {
                if (panel == null) return;
                bar.setIndeterminate(false);
                bar.setProgress(percent, true);
                status.setText("正在下载游戏资源  " + percent + "%");
            }
        });
    }

    void finishAndWait(final String detail, final boolean updated) {
        if (activity == null) return;
        ui.post(new Runnable() {
            @Override public void run() {
                if (panel == null) { hidden.countDown(); return; }
                status.setText(updated ? "资源更新完成，正在启动游戏" : detail);
                if (updated) {
                    bar.setIndeterminate(false);
                    bar.setProgress(100, true);
                }
                long elapsed = SystemClock.uptimeMillis() - shownAt;
                ui.postDelayed(new Runnable() {
                    @Override public void run() {
                        if (panel != null) {
                            ViewGroup parent = (ViewGroup) panel.getParent();
                            if (parent != null) parent.removeView(panel);
                            panel = null;
                        }
                        hidden.countDown();
                    }
                }, Math.max(450L, 850L - elapsed));
            }
        });
        try { hidden.await(1700, TimeUnit.MILLISECONDS); }
        catch (InterruptedException interrupted) { Thread.currentThread().interrupt(); }
    }

    private int dp(int value) {
        return Math.round(value * activity.getResources().getDisplayMetrics().density);
    }
}
