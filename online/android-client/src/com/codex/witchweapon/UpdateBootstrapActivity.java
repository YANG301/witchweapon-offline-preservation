package com.codex.witchweapon;

import android.app.Activity;
import android.content.Intent;
import android.os.Bundle;
import android.view.View;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.TextView;

/** Repair interrupted local updates, then let the original Unity loading UI check online resources. */
public final class UpdateBootstrapActivity extends Activity {
    private boolean checking;

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        OfflineApplication application = (OfflineApplication) getApplication();
        if (application.hasExistingGameActivity()) {
            openGame();
            return;
        }
        // No second resource-check screen on a healthy launch. The original
        // UILoadingAssetBundle scene stays visible while /getversion checks
        // and applies the signed release in OfflineApplication.
        getWindow().setBackgroundDrawableResource(android.R.color.black);
        checkLocalResources();
    }

    private void showRecoveryError(String message) {
        LinearLayout page = new LinearLayout(this);
        page.setOrientation(LinearLayout.VERTICAL);
        int padding = (int) (28 * getResources().getDisplayMetrics().density);
        page.setPadding(padding, padding, padding, padding);
        TextView status = new TextView(this);
        status.setText(message);
        status.setTextSize(18);
        page.addView(status);
        Button retry = new Button(this);
        retry.setText("重试");
        retry.setOnClickListener(new View.OnClickListener() {
            @Override public void onClick(View ignored) { checkLocalResources(); }
        });
        page.addView(retry);
        setContentView(page);
    }

    private void checkLocalResources() {
        if (checking) return;
        checking = true;
        new Thread(new Runnable() {
            @Override public void run() {
                AssetUpdateManager.Result result = AssetUpdateManager.recoverBeforeUnity(
                        UpdateBootstrapActivity.this);
                runOnUiThread(new Runnable() {
                    @Override public void run() {
                        if (isFinishing()) return;
                        checking = false;
                        if (result.safeToLaunch) openGame();
                        else showRecoveryError(result.detail);
                    }
                });
            }
        }, "witch-local-resource-recovery").start();
    }

    private void openGame() {
        Intent game = new Intent();
        game.setClassName(getPackageName(), "com.shuiqinling.ww.android.LingGameActivity");
        game.addFlags(Intent.FLAG_ACTIVITY_REORDER_TO_FRONT | Intent.FLAG_ACTIVITY_SINGLE_TOP);
        startActivity(game);
        finish();
    }
}
