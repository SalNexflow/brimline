"""A Bambu Lab printer in LAN mode, as described by COMMUNITY documentation (OpenBambuAPI; docs/DECISIONS.md
D164): the printer itself is the MQTT broker; clients log in as `bblp` with the LAN access code, publish
commands to `device/{serial}/request` and read `device/{serial}/report`.

A minimal MQTT 3.1.1 broker, written by hand (D167): CONNECT/CONNACK, SUBSCRIBE/SUBACK,
UNSUBSCRIBE/UNSUBACK, PUBLISH (QoS 0 and 1, with PUBACK), PINGREQ/PINGRESP, DISCONNECT. No retained
messages, wills or QoS 2. A real printer requires TLS on port 8883; the mock speaks plain MQTT.
"""

import contextlib
import json
import socket
import socketserver
import struct
import threading
from typing import Any

from brimline_engine.machines.config import MachineConfig
from brimline_engine.machines.sim import SimMachine, SimRefused, wait_or_hang

GCODE_STATE = {
    "idle": "IDLE",
    "running": "RUNNING",
    "done": "FINISH",
    "failed": "FAILED",
    "offline": "FAILED",
}


def _read_exact(sock: socket.socket, n: int) -> bytes:
    data = b""
    while len(data) < n:
        chunk = sock.recv(n - len(data))
        if not chunk:
            raise ConnectionError("closed")
        data += chunk
    return data


def _read_packet(sock: socket.socket) -> tuple[int, int, bytes]:
    """(type, flags, body) of one MQTT control packet."""
    first = _read_exact(sock, 1)[0]
    length, shift = 0, 0
    while True:  # "remaining length": up to four 7-bit groups
        byte = _read_exact(sock, 1)[0]
        length += (byte & 0x7F) << shift
        if not byte & 0x80:
            break
        shift += 7
        if shift > 21:
            raise ConnectionError("malformed remaining length")
    return first >> 4, first & 0x0F, _read_exact(sock, length)


def _packet(kind: int, flags: int, body: bytes) -> bytes:
    n, encoded = len(body), b""
    while True:
        digit, n = n % 128, n // 128
        encoded += bytes([digit | (0x80 if n else 0)])
        if not n:
            break
    return bytes([(kind << 4) | flags]) + encoded + body


def _string(body: bytes, i: int) -> tuple[str, int]:
    (n,) = struct.unpack_from("!H", body, i)
    return body[i + 2 : i + 2 + n].decode(), i + 2 + n


def _publish(topic: str, payload: bytes) -> bytes:
    t = topic.encode()
    return _packet(3, 0, struct.pack("!H", len(t)) + t + payload)


class RunningMqtt:
    def __init__(
        self,
        server: socketserver.ThreadingTCPServer,
        thread: threading.Thread,
        stop: threading.Event,
    ) -> None:
        self._server, self._thread, self._stop = server, thread, stop

    @property
    def port(self) -> int:
        return int(self._server.server_address[1])

    def stop(self) -> None:
        self._stop.set()
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)


def start(machine: SimMachine, cfg: MachineConfig, host: str, port: int) -> RunningMqtt:
    stop = threading.Event()
    request_topic = f"device/{cfg.serial}/request"
    report_topic = f"device/{cfg.serial}/report"
    lock = threading.Lock()
    subscribers: dict[int, tuple[socket.socket, set[str]]] = {}

    def report(extra: dict[str, Any]) -> None:
        data = _publish(report_topic, json.dumps(extra).encode())
        with lock:
            targets = [
                s for s, topics in subscribers.values() if report_topic in topics or "#" in topics
            ]
        for s in targets:
            with contextlib.suppress(OSError):
                s.sendall(data)

    def push_status(sequence_id: str) -> dict[str, Any]:
        s = machine.status()
        remaining = None
        if s.state == "running" and s.progress is not None and s.seconds:
            remaining = int((s.seconds / max(s.progress, 1e-6) - s.seconds) // 60)
        return {
            "print": {
                "command": "push_status",
                "sequence_id": sequence_id,
                "gcode_state": GCODE_STATE[s.state],
                "gcode_file": f"{s.job}.gcode" if s.job else "",
                "subtask_name": s.job or "",
                "mc_percent": 100 if s.state == "done" else int((s.progress or 0) * 100),
                "mc_remaining_time": remaining or 0,
                "print_error": 0 if s.state != "failed" else 0x0300_0001,
                "msg": 0,
            }
        }

    def command(message: dict[str, Any]) -> None:
        if "pushing" in message:
            seq = str(message["pushing"].get("sequence_id", "0"))
            report(push_status(seq))
            return
        p = message.get("print")
        if not isinstance(p, dict):
            return
        seq, cmd = str(p.get("sequence_id", "0")), p.get("command")
        result = "success"
        try:
            if cmd == "gcode_file":
                machine.start(str(p.get("param", "")).removesuffix(".gcode"))
            elif cmd == "stop":
                machine.stop()
            else:
                return
        except SimRefused as e:
            result = "failed"
            report(
                {"print": {"command": cmd, "sequence_id": seq, "result": result, "reason": str(e)}}
            )
            return
        report({"print": {"command": cmd, "sequence_id": seq, "result": result}})
        report(push_status(seq))

    class Handler(socketserver.BaseRequestHandler):
        def handle(self) -> None:
            sock: socket.socket = self.request
            key = id(sock)
            try:
                kind, _, body = _read_packet(sock)
                if kind != 1:
                    return
                if not wait_or_hang(machine, stop):
                    return
                sock.sendall(_packet(2, 0, bytes([0, self._login(body)])))
                if self._login(body) != 0:
                    return
                with lock:
                    subscribers[key] = (sock, set())
                while not stop.is_set():
                    kind, flags, body = _read_packet(sock)
                    if not wait_or_hang(machine, stop):
                        return
                    if kind == 8:  # SUBSCRIBE
                        pid, i, granted = body[:2], 2, b""
                        while i < len(body):
                            topic, i = _string(body, i)
                            i += 1  # requested QoS; we grant 0
                            with lock:
                                subscribers[key][1].add(topic)
                            granted += b"\x00"
                        sock.sendall(_packet(9, 0, pid + granted))
                    elif kind == 10:  # UNSUBSCRIBE
                        pid, i = body[:2], 2
                        while i < len(body):
                            topic, i = _string(body, i)
                            with lock:
                                subscribers[key][1].discard(topic)
                        sock.sendall(_packet(11, 0, pid))
                    elif kind == 3:  # PUBLISH
                        topic, i = _string(body, 0)
                        qos = (flags >> 1) & 0x03
                        if qos:
                            sock.sendall(_packet(4, 0, body[i : i + 2]))
                            i += 2
                        if topic == request_topic:
                            try:
                                message = json.loads(body[i:])
                            except json.JSONDecodeError:
                                continue
                            if isinstance(message, dict):
                                command(message)
                    elif kind == 12:  # PINGREQ
                        sock.sendall(_packet(13, 0, b""))
                    elif kind == 14:  # DISCONNECT
                        return
            except (ConnectionError, OSError, struct.error, UnicodeDecodeError):
                return
            finally:
                with lock:
                    subscribers.pop(key, None)

        def _login(self, body: bytes) -> int:
            """CONNACK return code: 0 accepted, 1 bad protocol, 4 bad user name or password."""
            name, i = _string(body, 0)
            if name != "MQTT" or body[i] != 4:
                return 1
            flags = body[i + 1]
            i += 4  # level, flags, keep alive
            _, i = _string(body, i)  # client id
            if flags & 0x04:  # will topic and message
                _, i = _string(body, i)
                _, i = _string(body, i)
            user = password = ""
            if flags & 0x80:
                user, i = _string(body, i)
            if flags & 0x40:
                password, i = _string(body, i)
            return 0 if (user, password) == ("bblp", cfg.access_code) else 4

    server = socketserver.ThreadingTCPServer((host, port), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, name=f"mock-{machine.code}", daemon=True)
    thread.start()
    return RunningMqtt(server, thread, stop)
