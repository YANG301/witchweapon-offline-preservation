package com.codex.witchweapon;

import android.content.Context;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.net.URI;
import java.net.URISyntaxException;
import java.net.URL;
import java.net.InetSocketAddress;
import java.net.Socket;
import javax.net.ssl.HttpsURLConnection;
import javax.net.ssl.SSLParameters;
import javax.net.ssl.SSLSocket;
import javax.net.ssl.SSLSocketFactory;

/** One public HTTPS origin, supplied by the APK build as an asset. */
final class OnlineEndpoint {
    private final String origin;
    private final URI originUri;

    private OnlineEndpoint(String origin) {
        this.origin = origin;
        this.originUri = URI.create(origin);
    }

    static OnlineEndpoint fromAssets(Context context) throws IOException {
        byte[] bytes;
        try (InputStream input = context.getAssets().open("online_endpoint.txt")) {
            ByteArrayOutputStream output = new ByteArrayOutputStream();
            byte[] buffer = new byte[512];
            int count;
            while ((count = input.read(buffer)) >= 0) {
                output.write(buffer, 0, count);
                if (output.size() > 512) throw new IOException("Endpoint configuration is too large");
            }
            bytes = output.toByteArray();
        }
        String value = new String(bytes, "UTF-8").trim();
        try {
            URI uri = new URI(value);
            if (!"https".equalsIgnoreCase(uri.getScheme()) || uri.getHost() == null
                    || uri.getHost().length() == 0 || uri.getRawUserInfo() != null
                    || uri.getRawQuery() != null || uri.getRawFragment() != null
                    || (uri.getRawPath() != null && !uri.getRawPath().isEmpty()
                        && !"/".equals(uri.getRawPath()))) {
                throw new IOException("The endpoint must be an HTTPS origin without credentials or path");
            }
            int port = uri.getPort();
            if (port != -1 && (port < 1 || port > 65535)) throw new IOException("Invalid HTTPS port");
            String normalized = uri.getScheme().toLowerCase() + "://" + uri.getRawAuthority();
            return new OnlineEndpoint(normalized);
        } catch (URISyntaxException error) {
            throw new IOException("Invalid endpoint configuration", error);
        }
    }

    HttpsURLConnection open(String path) throws IOException {
        if (path == null || !path.startsWith("/") || path.startsWith("//")
                || path.indexOf('?') >= 0 || path.indexOf('#') >= 0 || path.indexOf('\\') >= 0
                || path.contains("..")) {
            throw new IOException("Invalid remote path");
        }
        for (int i = 0; i < path.length(); i++) {
            char c = path.charAt(i);
            if (c < 33 || c > 126) throw new IOException("Invalid remote path character");
        }
        URL target = new URL(origin + path);
        HttpsURLConnection connection = (HttpsURLConnection) target.openConnection();
        // Keep Android's default CA and hostname verification. Never follow a
        // redirect with an Authorization header to another origin.
        connection.setInstanceFollowRedirects(false);
        connection.setConnectTimeout(10000);
        connection.setReadTimeout(20000);
        connection.setUseCaches(false);
        connection.setRequestProperty("Accept", "application/octet-stream, application/json");
        return connection;
    }

    String hostHeader() { return originUri.getRawAuthority(); }

    SSLSocket openChatSocket() throws IOException {
        String host = originUri.getHost();
        int port = originUri.getPort() < 0 ? 443 : originUri.getPort();
        Socket tcp = new Socket();
        try {
            tcp.connect(new InetSocketAddress(host, port), 10000);
            tcp.setSoTimeout(10000);
            SSLSocket tls = (SSLSocket) ((SSLSocketFactory) SSLSocketFactory.getDefault())
                    .createSocket(tcp, host, port, true);
            try {
                SSLParameters parameters = tls.getSSLParameters();
                parameters.setEndpointIdentificationAlgorithm("HTTPS");
                tls.setSSLParameters(parameters);
                tls.setSoTimeout(10000);
                tls.startHandshake();
                if (!HttpsURLConnection.getDefaultHostnameVerifier()
                        .verify(host, tls.getSession())) throw new IOException("HTTPS hostname mismatch");
                return tls;
            } catch (IOException failed) {
                tls.close();
                throw failed;
            }
        } catch (IOException failed) {
            tcp.close();
            throw failed;
        }
    }
}
