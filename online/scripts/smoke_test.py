"""真实本机 HTTP 冒烟检查；测试账号仅写入临时测试目录。"""
import argparse
import json
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXE = ROOT / "server/dist/witchweapon-server-windows-amd64.exe"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, default=EXE, help="服务端可执行文件路径")
    parser.add_argument("--stories", type=Path, default=ROOT / "data/stories.json", help="只读剧情文件路径")
    parser.add_argument("--scratch", type=Path, default=ROOT / "server",
                        help="已存在的临时父目录；测试在其下新建独立子目录并在退出时清理")
    args = parser.parse_args()
    binary, stories, scratch = args.binary.resolve(), args.stories.resolve(), args.scratch.resolve()
    if not binary.is_file() or not stories.is_file() or not scratch.is_dir():
        raise RuntimeError("请确认服务端、剧情文件与临时父目录均已存在。")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    origin = "http://127.0.0.1:%d" % port
    # 不使用 HTTP 代理转发本机测试凭据。
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    # scratch 仅作为父目录，绝不直接作为存档目录；成功或失败后清理新建子目录。
    with tempfile.TemporaryDirectory(prefix="http-test-", dir=str(scratch)) as state:
        def start():
            proc = subprocess.Popen([str(binary), "-listen", "127.0.0.1:%d" % port,
                                     "-data", state, "-stories", str(stories)],
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                for _ in range(120):
                    if proc.poll() is not None:
                        raise RuntimeError("服务端启动失败。")
                    try:
                        status, data = request("GET", "/health")
                        if status == 200 and data["status"] == "ok":
                            return proc
                    except urllib.error.URLError:
                        pass
                    time.sleep(0.05)
                raise RuntimeError("服务端健康检查超时")
            except BaseException:
                stop(proc)
                raise

        def stop(proc):
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=5)

        def request(method, path, body=None, token=None):
            headers = {"Content-Type": "application/json"}
            if token:
                headers["Authorization"] = "Bearer " + token
            req = urllib.request.Request(origin + path,
                                         data=None if body is None else json.dumps(body).encode("utf-8"),
                                         headers=headers, method=method)
            try:
                response = opener.open(req, timeout=20)
            except urllib.error.HTTPError as error:
                response = error
            with response:
                raw = response.read()
                return response.status, json.loads(raw) if raw else None

        process = start()
        try:
            password = "Smoke-Only-Password-4817"
            status, alice = request("POST", "/api/v1/auth/register", {"email": "Alice@example.test", "password": password})
            assert status == 201, "第一个测试账号注册失败。"
            status, bob = request("POST", "/api/v1/auth/register", {"email": "bob@example.test", "password": password})
            assert status == 201, "第二个测试账号注册失败。"
            assert alice["player"]["id"] != bob["player"]["id"]
            assert alice["player"]["email"] == "alice@example.test"
            assert alice["player"]["emailVerified"] is False
            assert request("GET", "/api/v1/stories")[0] == 401
            status, catalog = request("GET", "/api/v1/stories", token=alice["token"])
            assert status == 200 and len(catalog["stories"]) == 1
            story_id = catalog["stories"][0]["id"]
            status, story = request("GET", "/api/v1/stories/" + story_id, token=alice["token"])
            assert status == 200 and len(story["lines"]) == 9
            assert "科技" in story["lines"][0]["text"]
            status, player = request("PUT", "/api/v1/progress/" + story_id, {"lastLine": 8, "completed": True}, alice["token"])
            assert status == 200 and player["progress"][0]["completed"] is True
            status, other = request("GET", "/api/v1/me", token=bob["token"])
            assert status == 200 and other["progress"] == []
            assert request("PUT", "/api/v1/progress/" + story_id, {"lastLine": 9, "completed": True}, alice["token"])[0] == 400
            assert request("POST", "/api/v1/auth/login", {"email": "alice@example.test", "password": "wrong-password"})[0] == 401
            assert request("POST", "/api/v1/auth/logout", token=bob["token"])[0] == 204
            assert request("GET", "/api/v1/me", token=bob["token"])[0] == 401
            stop(process)
            process = start()
            assert request("GET", "/api/v1/me", token=alice["token"])[0] == 401
            status, logged_in = request("POST", "/api/v1/auth/login", {"email": "alice@example.test", "password": password})
            assert status == 200 and logged_in["player"]["progress"][0]["completed"] is True
            print("PASS：真实 HTTP 注册、登录、中文剧情、两账号隔离、边界校验、退出、重启存档及会话失效。")
        finally:
            stop(process)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("FAIL：测试已中断。", file=sys.stderr)
        sys.exit(130)
    except Exception:
        # 不打印异常或响应正文，以免暴露口令或会话 token。
        print("FAIL：HTTP 冒烟检查失败，请检查服务端、剧情与临时目录配置。", file=sys.stderr)
        sys.exit(1)
