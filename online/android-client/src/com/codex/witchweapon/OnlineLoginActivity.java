package com.codex.witchweapon;

import android.app.Activity;
import android.content.Intent;
import android.os.Bundle;
import android.text.InputType;
import android.view.View;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.nio.charset.StandardCharsets;
import javax.net.ssl.HttpsURLConnection;
import org.json.JSONObject;

/** Temporary native account entry until the original EncryptTools wire format is recovered. */
public final class OnlineLoginActivity extends Activity {
    private EditText emailInput;
    private EditText passwordInput;
    private TextView status;
    private Button loginButton;
    private Button registerButton;
    private boolean busy;

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        // Re-entering via the launcher must not switch accounts beneath an
        // already running Unity scene or replace its Lua mirror mid-request.
        if (((OfflineApplication) getApplication()).hasSession()) {
            Intent game = new Intent();
            game.setClassName(getPackageName(), "com.shuiqinling.ww.android.LingGameActivity");
            startActivity(game);
            finish();
            return;
        }
        LinearLayout content = new LinearLayout(this);
        content.setOrientation(LinearLayout.VERTICAL);
        int spacing = (int) (16 * getResources().getDisplayMetrics().density);
        content.setPadding(spacing, spacing, spacing, spacing);
        ScrollView scroll = new ScrollView(this);
        scroll.addView(content);
        setContentView(scroll);

        TextView heading = new TextView(this);
        heading.setText("魔女兵器 · 在线账号");
        heading.setTextSize(24);
        content.addView(heading);

        emailInput = new EditText(this);
        emailInput.setHint("邮箱");
        emailInput.setSingleLine(true);
        emailInput.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_EMAIL_ADDRESS);
        content.addView(emailInput);

        passwordInput = new EditText(this);
        passwordInput.setHint("密码（至少 12 个字符）");
        passwordInput.setSingleLine(true);
        passwordInput.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_PASSWORD);
        content.addView(passwordInput);

        LinearLayout actions = new LinearLayout(this);
        actions.setOrientation(LinearLayout.HORIZONTAL);
        loginButton = new Button(this);
        loginButton.setText("登录");
        registerButton = new Button(this);
        registerButton.setText("注册");
        actions.addView(loginButton);
        actions.addView(registerButton);
        content.addView(actions);

        status = new TextView(this);
        status.setText("在线测试版暂不验证邮箱归属。账号会话仅保留在本次进程内。");
        content.addView(status);
        loginButton.setOnClickListener(new View.OnClickListener() {
            @Override public void onClick(View ignored) { submit(false); }
        });
        registerButton.setOnClickListener(new View.OnClickListener() {
            @Override public void onClick(View ignored) { submit(true); }
        });

        if (((OfflineApplication) getApplication()).endpoint() == null) {
            status.setText("尚未配置有效 HTTPS 服务器地址，无法登录。请检查打包时的 online_endpoint.txt。");
            loginButton.setEnabled(false);
            registerButton.setEnabled(false);
        }
    }

    private void submit(final boolean register) {
        if (busy) return;
        final String email = emailInput.getText().toString().trim().toLowerCase(java.util.Locale.ROOT);
        final String password = passwordInput.getText().toString();
        if (email.indexOf('@') <= 0 || email.length() > 254
                || password.codePointCount(0, password.length()) < 12
                || password.codePointCount(0, password.length()) > 128) {
            status.setText("请输入有效邮箱和 12 至 128 个字符的密码。");
            return;
        }
        passwordInput.setText("");
        busy = true;
        loginButton.setEnabled(false);
        registerButton.setEnabled(false);
        status.setText(register ? "正在注册…" : "正在登录…");
        new Thread(new Runnable() {
            @Override public void run() { authenticate(email, password, register); }
        }, "witch-online-auth").start();
    }

    private void authenticate(String email, String password, boolean register) {
        HttpsURLConnection connection = null;
        String token = null;
        String message;
        try {
            OnlineEndpoint endpoint = ((OfflineApplication) getApplication()).endpoint();
            if (endpoint == null) throw new IllegalStateException("HTTPS endpoint unavailable");
            connection = endpoint.open("/api/v1/auth/" + (register ? "register" : "login"));
            connection.setRequestMethod("POST");
            connection.setDoOutput(true);
            connection.setRequestProperty("Content-Type", "application/json; charset=utf-8");
            JSONObject credentials = new JSONObject();
            credentials.put("email", email);
            credentials.put("password", password);
            byte[] body = credentials.toString().getBytes(StandardCharsets.UTF_8);
            connection.setFixedLengthStreamingMode(body.length);
            try (OutputStream output = connection.getOutputStream()) { output.write(body); }
            int code = connection.getResponseCode();
            if (code >= 200 && code < 300) {
                byte[] reply;
                try (InputStream input = connection.getInputStream()) {
                    reply = readBounded(input, 65536);
                }
                token = new JSONObject(new String(reply, StandardCharsets.UTF_8)).getString("token");
                if (token.isEmpty() || token.length() > 512) throw new IllegalStateException("Invalid session");
                ((OfflineApplication) getApplication()).prepareSession(token);
                message = "登录成功";
            } else {
                message = "服务器拒绝请求（HTTP " + code + "）。请检查账号或密码。";
            }
        } catch (Exception error) {
            // Deliberately do not log URLs, request bodies, headers or response text.
            token = null;
            message = "HTTPS 连接或服务器响应失败，请检查网络与服务器配置。";
        } finally {
            if (connection != null) connection.disconnect();
        }
        final String resultToken = token;
        final String resultMessage = message;
        runOnUiThread(new Runnable() {
            @Override public void run() {
                busy = false;
                if (resultToken != null) {
                    ((OfflineApplication) getApplication()).acceptSession(resultToken);
                    Intent game = new Intent();
                    game.setClassName(getPackageName(), "com.shuiqinling.ww.android.LingGameActivity");
                    startActivity(game);
                    finish();
                } else {
                    loginButton.setEnabled(true);
                    registerButton.setEnabled(true);
                    status.setText(resultMessage);
                }
            }
        });
    }

    private static byte[] readBounded(InputStream input, int limit) throws Exception {
        ByteArrayOutputStream output = new ByteArrayOutputStream();
        byte[] buffer = new byte[4096];
        int count;
        while ((count = input.read(buffer)) >= 0) {
            output.write(buffer, 0, count);
            if (output.size() > limit) throw new IllegalStateException("Response too large");
        }
        return output.toByteArray();
    }

    @Override public void onBackPressed() {
        status.setText("在线模式需要先登录账号。退出游戏请使用系统任务切换器。");
    }
}
