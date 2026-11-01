"""A GRBL 1.1 controller on a serial line, served over TCP (pyserial's socket:// URL reaches it), as in the
official interface wiki (docs/DECISIONS.md D166).

Real-time characters: `?` status report, `!` feed hold, `~` resume, 0x18 soft reset. Lines are answered
`ok` or `error:N`. A soft reset during motion leaves the machine in alarm 3 until `$X` unlocks it.
GRBL has no notion of a job; the simulation reads a comment line `(BRIMLINE JOB <job>)` at the top of the
streamed program to know which prepared job the program is (comments are ignored by real GRBL).
"""

import re
import socket
import socketserver
import threading

from brimline_engine.machines.config import MachineConfig
from brimline_engine.machines.sim import SimMachine, SimRefused, wait_or_hang

WELCOME = b"\r\nGrbl 1.1h ['$' for help]\r\n"
JOB_LINE = re.compile(r"\(BRIMLINE JOB ([A-Za-z0-9-]+)\)")


class RunningTcp:
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


def start(machine: SimMachine, cfg: MachineConfig, host: str, port: int) -> RunningTcp:
    stop = threading.Event()
    alarm = {"on": False}

    def report() -> bytes:
        s = machine.status()
        if alarm["on"] or s.state in ("failed", "offline"):
            word = "Alarm"
        else:
            word = "Run" if s.state == "running" else "Idle"
        return f"<{word}|MPos:0.000,0.000,0.000|FS:0,0>\r\n".encode()

    class Handler(socketserver.BaseRequestHandler):
        def handle(self) -> None:
            sock: socket.socket = self.request
            sock.settimeout(0.2)
            if not wait_or_hang(machine, stop):
                return
            sock.sendall(WELCOME)
            line = b""
            while not stop.is_set():
                try:
                    data = sock.recv(256)
                except TimeoutError:
                    continue
                except OSError:
                    return
                if not data:
                    return
                for byte in data:
                    ch = bytes([byte])
                    if ch in (b"?", b"!", b"~", b"\x18"):
                        if not wait_or_hang(machine, stop):
                            return
                        sock.sendall(self._realtime(ch))
                    elif ch == b"\n":
                        if not wait_or_hang(machine, stop):
                            return
                        sock.sendall(self._line(line.decode(errors="replace").strip()))
                        line = b""
                    elif ch != b"\r":
                        line += ch

        def _realtime(self, ch: bytes) -> bytes:
            if ch == b"?":
                return report()
            if ch == b"\x18":  # soft reset: a job in motion is lost and the machine alarms
                try:
                    machine.stop()
                    alarm["on"] = True
                    return b"ALARM:3\r\n" + WELCOME
                except SimRefused:
                    return WELCOME
            return b""  # '!' and '~' answer nothing; the next status report shows the state

        def _line(self, text: str) -> bytes:
            if not text:
                return b"ok\r\n"
            if text == "$X":
                alarm["on"] = False
                return b"[MSG:Caution: Unlocked]\r\nok\r\n"
            if alarm["on"]:
                return b"error:9\r\n"  # G-code locked out during alarm
            m = JOB_LINE.fullmatch(text)
            if m:
                try:
                    machine.start(m.group(1))
                except SimRefused:
                    return b"error:9\r\n"
            return b"ok\r\n"

    server = socketserver.ThreadingTCPServer((host, port), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, name=f"mock-{machine.code}", daemon=True)
    thread.start()
    return RunningTcp(server, thread, stop)
