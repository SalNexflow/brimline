"""OctoPrint's REST API, as documented (docs/DECISIONS.md D161), for one simulated printer."""

import re
from http.server import BaseHTTPRequestHandler

from brimline_engine.machines.config import MachineConfig
from brimline_engine.machines.mocks.http import Answer, Route, Running, serve
from brimline_engine.machines.sim import SimMachine, SimRefused

STATE_TEXT = {
    "idle": "Operational",
    "done": "Operational",
    "running": "Printing",
    "failed": "Error",
}


def start(machine: SimMachine, cfg: MachineConfig, host: str, port: int) -> Running:
    def printer(_: re.Match[str], __: object) -> Answer:
        s = machine.status()
        printing = s.state == "running"
        return 200, {
            "state": {
                "text": STATE_TEXT.get(s.state, "Offline"),
                "flags": {
                    "operational": s.state != "offline",
                    "printing": printing,
                    "paused": False,
                    "cancelling": False,
                    "pausing": False,
                    "sdReady": False,
                    "error": s.state == "failed",
                    "ready": s.state in ("idle", "done"),
                    "closedOrError": s.state in ("failed", "offline"),
                },
            },
            "temperature": {
                "tool0": {
                    "actual": 214.8 if printing else 24.0,
                    "target": 215.0 if printing else 0.0,
                },
                "bed": {"actual": 59.9 if printing else 23.0, "target": 60.0 if printing else 0.0},
            },
        }

    def job(_: re.Match[str], __: object) -> Answer:
        s = machine.status()
        name = f"{s.job}.gcode" if s.job else None
        completion = (
            100.0 if s.state == "done" else (None if s.progress is None else s.progress * 100)
        )
        return 200, {
            "job": {"file": {"name": name, "origin": "local" if name else None}},
            "progress": {"completion": completion, "printTime": s.seconds, "printTimeLeft": None},
            "state": STATE_TEXT.get(s.state, "Offline"),
            "error": s.message if s.state == "failed" else None,
        }

    def select(m: re.Match[str], body: object) -> Answer:
        if not isinstance(body, dict) or body.get("command") != "select":
            return 400, {"error": "unknown command"}
        name = m.group(1)
        if not name.endswith(".gcode") or name[:-6] not in machine.files:
            return 404, {"error": "file not found"}
        if body.get("print"):
            try:
                machine.start(name[:-6])
            except SimRefused as e:
                return 409, {"error": str(e)}
        return 204, None

    def command(_: re.Match[str], body: object) -> Answer:
        if not isinstance(body, dict) or body.get("command") != "cancel":
            return 400, {"error": "unknown command"}
        try:
            machine.stop()
        except SimRefused as e:
            return 409, {"error": str(e)}
        return 204, None

    def authorised(request: BaseHTTPRequestHandler) -> tuple[bool, dict[str, str]]:
        return request.headers.get("X-Api-Key") == cfg.api_key, {}

    routes = [
        Route("GET", r"/api/printer", printer),
        Route("GET", r"/api/job", job),
        Route("POST", r"/api/files/local/([^/]+)", select),
        Route("POST", r"/api/job", command),
    ]
    return serve(machine, host, port, routes, authorised)
