"""Build a local-only Android client from the pinned, signed v4 candidate.

Only classes2.dex and assets/online_endpoint.txt may change. OnlineEndpoint
is compiled from a temporary copy with the local proxy certificate as its
sole trust anchor; the production Java source and signed candidate stay intact.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import ssl
import time
import zipfile

import build_online_apk as adapter
import build_original_ui_quest_refresh_v6_apk as signer
import build_original_ui_lottery_touch_probe_apk as touch
import build_priced_draw_apk as draw
from build_original_ui_lottery_lua_input_probe_apk import cert_digest


HERE = Path(__file__).resolve().parent
SOURCE = HERE / "build/witchweapon-online-bugfix-v4-test.apk"
SOURCE_SHA256 = "ba4ab0878301dbf06075714008ea57fa0aac9665846179cc129f9eab9164d748"
SOURCE_DEX_SHA256 = "21707cf87f9a41f9685c64f1494be0aafc3e2e18af5d23c8929762f69f2aa8b9"
ONLINE_ENDPOINT = HERE / "src/com/codex/witchweapon/OnlineEndpoint.java"
ONLINE_ENDPOINT_SHA256 = "5c0adf8bd9194103a5462bfe6770ee5bf2400043b8cc88b0d3c83c909898740a"
CERT = Path(r"D:\Project\魔女兵器在线版\测试服\HTTPS代理\cert-v2.pem")
# Fixed after generating the loopback proxy certificate. A replacement cert
# requires an explicit review and new test build; it cannot be silently used.
EXPECTED_CERT_DER_SHA256 = "d0a0838496895271ff4e7d3c278d9a872bbccfad665e55b1f4278de79c8c7b13"
TEMP = Path(r"D:\Environment\Android\temp\witch-online-local-staging-v4")
RESULT = HERE / "build/witchweapon-online-local-staging-v4.apk"
REPORT = HERE / "build/本地测试服客户端验收-v4.json"
ORIGIN = "https://127.0.0.1:19443"
OLD_ORIGIN = b"https://212.192.15.11:18443\n"
DEX = "classes2.dex"
ENDPOINT_ASSET = "assets/online_endpoint.txt"


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def replace_once(source: str, old: str, new: str) -> str:
    if source.count(old) != 1:
        raise ValueError("Staging Java anchor is missing or ambiguous: " + old[:80])
    return source.replace(old, new, 1)


def load_cert() -> tuple[bytes, str]:
    if not CERT.is_file():
        raise FileNotFoundError("Local HTTPS proxy certificate is absent: " + str(CERT))
    pem = CERT.read_text(encoding="ascii")
    if pem.count("-----BEGIN CERTIFICATE-----") != 1:
        raise ValueError("Expected exactly one PEM certificate")
    der = ssl.PEM_cert_to_DER_cert(pem)
    digest = sha256(der)
    if digest != EXPECTED_CERT_DER_SHA256:
        raise ValueError("Loopback proxy certificate differs from reviewed fingerprint: " + digest)
    parsed = ssl._ssl._test_decode_cert(str(CERT))
    san = parsed.get("subjectAltName", ())
    if ("IP Address", "127.0.0.1") not in san:
        raise ValueError("Local proxy certificate has no 127.0.0.1 IP SAN")
    now = time.time()
    if now < ssl.cert_time_to_seconds(parsed["notBefore"]) or \
            now > ssl.cert_time_to_seconds(parsed["notAfter"]):
        raise ValueError("Local proxy certificate is outside its validity window")
    return der, digest


def staging_endpoint_source(cert_der: bytes) -> Path:
    if adapter.sha256(ONLINE_ENDPOINT) != ONLINE_ENDPOINT_SHA256:
        raise ValueError("Production OnlineEndpoint.java changed")
    source = ONLINE_ENDPOINT.read_text(encoding="utf-8")
    source = replace_once(source, "import java.io.ByteArrayOutputStream;",
                          "import java.io.ByteArrayOutputStream;\nimport java.io.ByteArrayInputStream;")
    source = replace_once(source, "import java.net.Socket;", """import java.net.Socket;
import java.security.KeyStore;
import java.security.SecureRandom;
import java.security.cert.Certificate;
import java.security.cert.CertificateFactory;
import javax.net.ssl.SSLContext;
import javax.net.ssl.TrustManagerFactory;""")
    source = replace_once(source,
        "    private final URI originUri;\n\n    private OnlineEndpoint(String origin) {\n"
        "        this.origin = origin;\n        this.originUri = URI.create(origin);\n    }",
        "    private final URI originUri;\n    private final SSLSocketFactory stagingFactory;\n\n"
        "    private OnlineEndpoint(String origin) throws IOException {\n"
        "        this.origin = origin;\n        this.originUri = URI.create(origin);\n"
        "        this.stagingFactory = createPinnedFactory();\n    }")
    source = replace_once(source,
        "            return new OnlineEndpoint(normalized);",
        "            if (!\"" + ORIGIN + "\".equals(normalized))\n"
        "                throw new IOException(\"Staging accepts loopback HTTPS only\");\n"
        "            return new OnlineEndpoint(normalized);")
    source = replace_once(source,
        "        HttpsURLConnection connection = (HttpsURLConnection) target.openConnection();",
        "        HttpsURLConnection connection = (HttpsURLConnection) target.openConnection();\n"
        "        connection.setSSLSocketFactory(stagingFactory);")
    source = replace_once(source,
        "        // Keep Android's default CA and hostname verification. Never follow a\n"
        "        // redirect with an Authorization header to another origin.",
        "        // The test certificate is the only trust anchor. Android keeps its\n"
        "        // default hostname verifier; authenticated redirects remain disabled.")
    source = replace_once(source,
        "((SSLSocketFactory) SSLSocketFactory.getDefault())\n"
        "                    .createSocket(tcp, host, port, true)",
        "stagingFactory.createSocket(tcp, host, port, true)")
    # android.util.Base64 exists on every supported Android API level; the
    # cert's private key is never included in this test APK.
    cert_base64 = __import__("base64").b64encode(cert_der).decode("ascii")
    method = """
    private static SSLSocketFactory createPinnedFactory() throws IOException {
        try {
            byte[] der = android.util.Base64.decode("CERT_BASE64", android.util.Base64.NO_WRAP);
            Certificate cert = CertificateFactory.getInstance("X.509")
                    .generateCertificate(new ByteArrayInputStream(der));
            KeyStore store = KeyStore.getInstance(KeyStore.getDefaultType());
            store.load(null, null);
            store.setCertificateEntry("local-staging", cert);
            TrustManagerFactory managers = TrustManagerFactory.getInstance(
                    TrustManagerFactory.getDefaultAlgorithm());
            managers.init(store);
            SSLContext context = SSLContext.getInstance("TLS");
            context.init(null, managers.getTrustManagers(), new SecureRandom());
            return context.getSocketFactory();
        } catch (Exception failure) {
            throw new IOException("Local staging TLS pin initialization failed", failure);
        }
    }
""".replace("CERT_BASE64", cert_base64)
    if not source.endswith("}\n"):
        raise ValueError("Unexpected Java source ending")
    source = source[:-2] + method + "}\n"
    target = TEMP / "staging-source/com/codex/witchweapon/OnlineEndpoint.java"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(source, encoding="utf-8")
    return target


def compile_candidate(cert_der: bytes, old_dex: bytes) -> tuple[bytes, dict[str, str]]:
    old_classes = set(adapter.dex_classes(old_dex))
    if not {"Lcom/codex/witchweapon/OnlineEndpoint;",
            "Lcom/codex/witchweapon/DrawRequestIdempotency;"}.issubset(old_classes):
        raise ValueError("Expected inherited classes are absent")
    adapter.TEMP = TEMP
    draw.TEMP = TEMP
    copied_app = draw.java_source(True)
    common = [copied_app, touch.TRACE]
    common.extend(HERE / "src/com/codex/witchweapon" / name
                  for name in adapter.ADAPTER if name not in
                  ("OfflineApplication.java", "OnlineEndpoint.java"))
    common.extend(adapter.AUTHOR / name for name in adapter.AUTHOR_HELPERS)
    common.append(draw.BRIDGE)
    baseline_sources = [*common, ONLINE_ENDPOINT]
    baseline, baseline_classes = adapter.compile_dex(baseline_sources, old_classes)
    if baseline != old_dex or set(baseline_classes) != old_classes:
        raise ValueError("Current Java sources do not reproduce pinned v4 DEX")
    staged_source = staging_endpoint_source(cert_der)
    staged, new_classes = adapter.compile_dex([*common, staged_source], old_classes)
    if set(new_classes) != old_classes or staged == old_dex:
        raise ValueError("Staging DEX classes changed beyond the pinned endpoint")
    return staged, {"sourceDexSha256": sha256(old_dex),
                    "stagingDexSha256": sha256(staged)}


def prepare() -> tuple[dict[str, bytes], dict[str, str]]:
    if adapter.sha256(SOURCE) != SOURCE_SHA256:
        raise ValueError("Signed v4 candidate is missing or changed")
    cert_der, cert_sha = load_cert()
    with zipfile.ZipFile(SOURCE) as apk:
        if len(apk.namelist()) != len(set(apk.namelist())):
            raise ValueError("Duplicate APK members")
        if apk.read(ENDPOINT_ASSET) != OLD_ORIGIN:
            raise ValueError("Unexpected v4 endpoint asset")
        old_dex = apk.read(DEX)
    if sha256(old_dex) != SOURCE_DEX_SHA256:
        raise ValueError("Unexpected v4 DEX")
    staged_dex, dex_record = compile_candidate(cert_der, old_dex)
    return {DEX: staged_dex, ENDPOINT_ASSET: (ORIGIN + "\n").encode("ascii")}, \
           {"stagingOrigin": ORIGIN, "pinnedCertificateDerSha256": cert_sha,
            **dex_record}


def build(changes: dict[str, bytes], detail: dict[str, str]) -> dict:
    signer.SOURCE = SOURCE
    signer.SOURCE_SHA256 = SOURCE_SHA256
    signer.TEMP = TEMP
    report = signer.build(changes, RESULT, REPORT)
    before = cert_digest(signer.run([
        signer.JAVA, "-jar", signer.TOOLS / "lib/apksigner.jar",
        "verify", "--print-certs", SOURCE], signer.signer_env()))
    after = cert_digest(signer.run([
        signer.JAVA, "-jar", signer.TOOLS / "lib/apksigner.jar",
        "verify", "--print-certs", RESULT], signer.signer_env()))
    if before != after:
        raise ValueError("APK signer changed")
    with zipfile.ZipFile(SOURCE) as original, zipfile.ZipFile(RESULT) as staged:
        if staged.read(ENDPOINT_ASSET) != changes[ENDPOINT_ASSET]:
            raise ValueError("Staging APK endpoint differs")
        for member in ("AndroidManifest.xml", "classes.dex", "assets/m.assets_list.txt"):
            if original.read(member) != staged.read(member):
                raise ValueError("Unrelated APK payload changed: " + member)
    report.update(detail)
    report["signerCertificateSha256"] = after
    report["runtimeValidated"] = False
    for stale in ("changedUnityTextAsset", "originalUnityTextAssetSha256",
                  "preservesV4TaskItemPatch", "nativeRefreshClass"):
        report.pop(stale, None)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                      encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", action="store_true")
    args = parser.parse_args()
    if TEMP.exists():
        raise ValueError("Stale staging build directory; inspect it before cleanup")
    try:
        changes, detail = prepare()
        if args.build:
            report = build(changes, detail)
            print("LOCAL_STAGING_V4_APK_READY", report["testApk"]["sha256"])
        else:
            print("LOCAL_STAGING_V4_STATIC_OK", json.dumps(detail, sort_keys=True))
    finally:
        if TEMP.exists():
            resolved = TEMP.resolve()
            if resolved.parent != Path(r"D:\Environment\Android\temp").resolve() or \
                    resolved.name != "witch-online-local-staging-v4":
                raise ValueError("Unsafe staging temp cleanup target")
            shutil.rmtree(resolved)


if __name__ == "__main__":
    main()
