"""Local-only probe for the preserved client's LeanCloud RTM handshake.

Run with an ADB reverse mapping from the emulator to this loopback listener.
The probe logs command names and JSON field names only; it never logs message
content, account names, tokens, or the historical LeanCloud application ID.
It uses synthetic history and never forwards player messages to a public
service.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import struct
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit


MAGIC = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


def read_exact(stream, count: int) -> bytes:
    value = stream.read(count)
    if len(value) != count:
        raise EOFError("websocket closed")
    return value


def next_frame(stream):
    first, second = read_exact(stream, 2)
    opcode = first & 0x0F
    length = second & 0x7F
    if length == 126:
        length = struct.unpack("!H", read_exact(stream, 2))[0]
    elif length == 127:
        length = struct.unpack("!Q", read_exact(stream, 8))[0]
    if length > 65536:
        raise ValueError("frame too large")
    mask = read_exact(stream, 4) if second & 0x80 else None
    payload = read_exact(stream, length)
    if mask:
        payload = bytes(item ^ mask[index % 4] for index, item in enumerate(payload))
    return opcode, payload


def send_frame(stream, opcode: int, payload: bytes = b""):
    if len(payload) < 126:
        header = bytes((0x80 | opcode, len(payload)))
    else:
        header = bytes((0x80 | opcode, 126)) + struct.pack("!H", len(payload))
    stream.write(header + payload)
    stream.flush()


def schema(value):
    if isinstance(value, dict):
        return {key: schema(item) if isinstance(item, (dict, list)) else type(item).__name__
                for key, item in value.items()}
    if isinstance(value, list):
        return [schema(value[0])] if value else []
    return type(value).__name__


class Probe(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, format, *args):
        # BaseHTTPRequestHandler's default includes the raw path and query.
        pass

    def do_GET(self):
        path = urlsplit(self.path).path
        print(json.dumps({"event": "http", "path": path,
                          "queryKeys": sorted(parse_qs(urlsplit(self.path).query).keys())},
                         ensure_ascii=False), flush=True)
        if self.headers.get("Upgrade", "").lower() == "websocket":
            self.websocket(path)
            return
        if path.endswith("/v1/route"):
            host, port = self.server.server_address
            server = "ws://127.0.0.1:%d/rtm" % port
            body = json.dumps({"groupId": "ww-chat", "server": server, "secondary": server,
                               "ttl": 3600, "expire": int(time.time()) + 3600},
                              separators=(",", ":")).encode("ascii")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_error(404)

    def websocket(self, path: str):
        key = self.headers.get("Sec-WebSocket-Key", "")
        if not key or len(key) > 128:
            self.send_error(400)
            return
        options = [value.strip() for value in self.headers.get(
            "Sec-WebSocket-Protocol", "").split(",") if value.strip()]
        subprotocol = parse_qs(urlsplit(self.path).query).get("subprotocol", [""])[0]
        print(json.dumps({"event": "websocket", "path": path,
                          "subprotocols": options,
                          "querySubprotocol": subprotocol,
                          "headerKeys": sorted(self.headers.keys()),
                          "hasOrigin": self.headers.get("Origin") is not None},
                         ensure_ascii=False), flush=True)
        accept = base64.b64encode(hashlib.sha1((key + MAGIC).encode("ascii")).digest()).decode("ascii")
        self.send_response(101, "Switching Protocols")
        self.send_header("Upgrade", "websocket")
        self.send_header("Connection", "Upgrade")
        self.send_header("Sec-WebSocket-Accept", accept)
        if options:
            self.send_header("Sec-WebSocket-Protocol", options[0])
        self.end_headers()
        try:
            while True:
                opcode, payload = next_frame(self.rfile)
                if opcode == 8:
                    break
                if opcode == 9:
                    send_frame(self.wfile, 10, payload)
                    continue
                if opcode == 1:
                    try:
                        command = json.loads(payload.decode("utf-8"))
                        fields = schema(command)
                        if command.get("cmd") == "direct" and isinstance(command.get("msg"), str):
                            try:
                                fields["msg"] = schema(json.loads(command["msg"]))
                            except (UnicodeError, ValueError):
                                fields["msg"] = "non-json-string"
                        print(json.dumps({"event": "command", "cmd": command.get("cmd"),
                                          "op": command.get("op"), "i": command.get("i"),
                                          "fields": fields}, ensure_ascii=False), flush=True)
                        if command.get("cmd") == "session" and command.get("op") == "open":
                            reply = {"cmd": "session", "op": "opened", "i": command.get("i"),
                                     "st": "local-probe-session", "stTtl": 3600}
                            send_frame(self.wfile, 1, json.dumps(reply,
                                       separators=(",", ":")).encode("utf-8"))
                            print('{"event":"reply","cmd":"session","op":"opened"}',
                                  flush=True)
                        elif command.get("cmd") == "conv" and command.get("op") == "query":
                            cid = command.get("where", {}).get("objectId")
                            if cid in ("xinfengzhou-world", "xinfengzhou-system",
                                       "xinfengzhou-notify"):
                                reply = {"cmd": "conv", "op": "queried", "i": command.get("i"),
                                         "results": [{"objectId": cid}]}
                                send_frame(self.wfile, 1, json.dumps(reply,
                                           separators=(",", ":")).encode("utf-8"))
                                print('{"event":"reply","cmd":"conv","op":"queried"}',
                                      flush=True)
                        elif command.get("cmd") == "conv" and command.get("op") == "add":
                            reply = {"cmd": "conv", "op": "added", "i": command.get("i")}
                            send_frame(self.wfile, 1, json.dumps(reply,
                                       separators=(",", ":")).encode("utf-8"))
                            print('{"event":"reply","cmd":"conv","op":"added"}',
                                  flush=True)
                        elif command.get("cmd") == "logs":
                            history = []
                            if command.get("cid") == "xinfengzhou-world":
                                typed = {"_lctype": 2, "ChatContent": "本机协议验证，不会发送给其他玩家",
                                         "ChannelType": 0, "Name": "本机测试", "idRole": "0",
                                         "roleLv": 20, "Head": 0, "HeadBox": 0}
                                history.append({"data": json.dumps(typed, ensure_ascii=False,
                                                     separators=(",", ":")),
                                                "cid": "xinfengzhou-world", "from": "0",
                                                "timestamp": int(time.time() * 1000),
                                                "id": "local-probe-history-1"})
                            reply = {"cmd": "logs", "i": command.get("i"), "logs": history}
                            send_frame(self.wfile, 1, json.dumps(reply,
                                       separators=(",", ":")).encode("utf-8"))
                            print('{"event":"reply","cmd":"logs"}', flush=True)
                            if command.get("cid") == "xinfengzhou-world":
                                live = {"_lctype": 2, "ChatContent": "本机实时消息（隔离测试）",
                                        "ChannelType": 0, "Name": "本机测试", "idRole": "0",
                                        "roleLv": 20, "Head": 0, "HeadBox": 0}
                                push = {"cmd": "direct", "cid": "xinfengzhou-world",
                                        "fromPeerId": "0", "id": "local-probe-live-1",
                                        "timestamp": int(time.time() * 1000),
                                        "msg": json.dumps(live, ensure_ascii=False,
                                                          separators=(",", ":"))}
                                time.sleep(0.5)
                                send_frame(self.wfile, 1, json.dumps(push,
                                           ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
                                print('{"event":"push","cmd":"direct"}', flush=True)
                        elif command.get("cmd") == "direct":
                            reply = {"cmd": "direct", "i": command.get("i"),
                                     "uid": "local-probe-direct-1", "t": int(time.time() * 1000)}
                            send_frame(self.wfile, 1, json.dumps(reply,
                                       separators=(",", ":")).encode("utf-8"))
                            print('{"event":"reply","cmd":"direct"}', flush=True)
                    except (UnicodeError, ValueError, AttributeError):
                        print('{"event":"invalid_text_frame"}', flush=True)
                else:
                    print(json.dumps({"event": "frame", "opcode": opcode,
                                      "bytes": len(payload)}), flush=True)
        except (EOFError, OSError, ValueError):
            pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=18301)
    args = parser.parse_args()
    with ThreadingHTTPServer(("127.0.0.1", args.port), Probe) as server:
        print(json.dumps({"event": "listening", "port": args.port}), flush=True)
        server.serve_forever(poll_interval=0.25)


if __name__ == "__main__":
    main()
