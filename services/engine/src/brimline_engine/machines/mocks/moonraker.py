"""Moonraker's websocket JSON-RPC 2.0 API at /websocket, as documented (docs/DECISIONS.md D162), for one
simulated Klipper printer: printer.objects.query (print_stats), printer.print.start, printer.print.cancel."""

import json
import threading
import time
from typing import Any

from websockets.exceptions import ConnectionClosed
from websockets.sync.server import Server, ServerConnection, serve

from brimline_engine.machines.config import MachineConfig
from brimline_engine.machines.sim import SimMachine, SimRefused, wait_or_hang

PRINT_STATE = {
    "idle": "standby",
    "running": "printing",
    "done": "complete",
    "failed": "error",
    "offline": "error",
}


class RunningWs:
    def __init__(self, server: Server, thread: threading.Thread, stop: threading.Event) -> None:
        self._server, self._thread, self._stop = server, thread, stop

    @property
    def port(self) -> int:
        return int(self._server.socket.getsockname()[1])

    def stop(self) -> None:
        self._stop.set()
        self._server.shutdown()
        self._thread.join(timeout=5)


def _result(machine: SimMachine, method: str, params: object) -> dict[str, Any]:
    if method == "printer.objects.query":
        s = machine.status()
        stats = {
            "filename": f"{s.job}.gcode" if s.job else "",
            "state": PRINT_STATE[s.state],
            "print_duration": float(s.seconds or 0),
            "message": s.message if s.state == "failed" else "",
        }
        return {"result": {"eventtime": time.monotonic(), "status": {"print_stats": stats}}}
    if method == "printer.print.start":
        name = params.get("filename", "") if isinstance(params, dict) else ""
        try:
            machine.start(str(name).removesuffix(".gcode"))
        except SimRefused as e:
            return {"error": {"code": 400, "message": str(e)}}
        return {"result": "ok"}
    if method == "printer.print.cancel":
        try:
            machine.stop()
        except SimRefused as e:
            return {"error": {"code": 400, "message": str(e)}}
        return {"result": "ok"}
    return {"error": {"code": -32601, "message": f"Method not found: {method}"}}


def start(machine: SimMachine, cfg: MachineConfig, host: str, port: int) -> RunningWs:
    stop = threading.Event()

    def handler(ws: ServerConnection) -> None:
        if ws.request is None or ws.request.path != "/websocket":
            ws.close(1008, "unknown path")
            return
        try:
            for frame in ws:
                if not wait_or_hang(machine, stop):
                    return
                try:
                    req = json.loads(frame)
                except (json.JSONDecodeError, TypeError):
                    ws.send(
                        json.dumps(
                            {"jsonrpc": "2.0", "error": {"code": -32700, "message": "Parse error"}}
                        )
                    )
                    continue
                reply = _result(machine, str(req.get("method", "")), req.get("params"))
                ws.send(json.dumps({"jsonrpc": "2.0", "id": req.get("id"), **reply}))
        except ConnectionClosed:
            return

    server = serve(handler, host, port)
    thread = threading.Thread(target=server.serve_forever, name=f"mock-{machine.code}", daemon=True)
    thread.start()
    return RunningWs(server, thread, stop)
