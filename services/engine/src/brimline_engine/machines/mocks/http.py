"""A tiny threaded HTTP server for the REST mocks (OctoPrint, PrusaLink, Formlabs). Standard library only.

Each mock gives a list of routes; a route answers with (status, JSON body or None). The simulated machine's
mode decides whether an answer comes at once, late, or never (machines/sim.py).
"""

import json
import re
import threading
from collections.abc import Callable
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from brimline_engine.machines.sim import SimMachine, wait_or_hang

Answer = tuple[int, object]  # (status, JSON body or None for an empty body)
Handler = Callable[[re.Match[str], object], Answer]


@dataclass(frozen=True)
class Route:
    method: str
    pattern: str  # a regular expression matched against the whole path
    handle: Handler


class Running:
    """A mock server running in its own thread; `stop()` ends it and any request left hanging."""

    def __init__(
        self, server: ThreadingHTTPServer, thread: threading.Thread, stop: threading.Event
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


def serve(
    machine: SimMachine,
    host: str,
    port: int,
    routes: list[Route],
    authorised: Callable[[BaseHTTPRequestHandler], tuple[bool, dict[str, str]]],
) -> Running:
    """`authorised(request)` returns (ok, headers to send with a 401 when not ok)."""
    stop = threading.Event()

    class RequestHandler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:
            pass  # quiet: tests and the engine log their own story

        def _answer(self, method: str) -> None:
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b""
            if not wait_or_hang(machine, stop):
                return  # unresponsive: never answer
            ok, challenge = authorised(self)
            if not ok:
                self._send(401, {"error": "unauthorized"}, challenge)
                return
            path = self.path.split("?", 1)[0]
            for r in routes:
                m = re.fullmatch(r.pattern, path)
                if r.method == method and m:
                    try:
                        body = json.loads(raw) if raw else None
                    except json.JSONDecodeError:
                        self._send(400, {"error": "invalid JSON"})
                        return
                    status, out = r.handle(m, body)
                    self._send(status, out)
                    return
            self._send(404, {"error": "not found"})

        def _send(self, status: int, body: object, headers: dict[str, str] | None = None) -> None:
            data = b"" if body is None else json.dumps(body).encode()
            self.send_response(status)
            for k, v in (headers or {}).items():
                self.send_header(k, v)
            if body is not None:
                self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self) -> None:
            self._answer("GET")

        def do_POST(self) -> None:
            self._answer("POST")

        def do_DELETE(self) -> None:
            self._answer("DELETE")

    server = ThreadingHTTPServer((host, port), RequestHandler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, name=f"mock-{machine.code}", daemon=True)
    thread.start()
    return Running(server, thread, stop)
