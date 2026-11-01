"""PrusaLink's v1 REST API, as specified (docs/DECISIONS.md D163), with HTTP Digest authentication
(RFC 7616, MD5, qop=auth), for one simulated printer."""

import hashlib
import re
import secrets
from http.server import BaseHTTPRequestHandler
from typing import Any

from brimline_engine.machines.config import MachineConfig
from brimline_engine.machines.mocks.http import Answer, Route, Running, serve
from brimline_engine.machines.sim import SimMachine, SimRefused, SimStatus

REALM = "Printer API"
PRINTER_STATE = {
    "idle": "IDLE",
    "running": "PRINTING",
    "done": "FINISHED",
    "failed": "ERROR",
    "offline": "ATTENTION",
}


def _md5(text: str) -> str:
    return hashlib.md5(text.encode()).hexdigest()


def _fields(header: str) -> dict[str, str]:
    return {k: v.strip('"') for k, v in re.findall(r'(\w+)=("[^"]*"|[^,\s]+)', header)}


def start(machine: SimMachine, cfg: MachineConfig, host: str, port: int) -> Running:
    nonce = secrets.token_hex(16)
    ids = {"next": 1, "current": 0}

    def authorised(request: BaseHTTPRequestHandler) -> tuple[bool, dict[str, str]]:
        challenge = {
            "WWW-Authenticate": f'Digest realm="{REALM}", nonce="{nonce}", qop="auth", algorithm=MD5'
        }
        header = request.headers.get("Authorization", "")
        if not header.startswith("Digest "):
            return False, challenge
        f = _fields(header[7:])
        if f.get("username") != cfg.username or f.get("nonce") != nonce:
            return False, challenge
        ha1 = _md5(f"{cfg.username}:{REALM}:{cfg.password}")
        ha2 = _md5(f"{request.command}:{f.get('uri', '')}")
        parts = [ha1, nonce, f.get("nc", ""), f.get("cnonce", ""), f.get("qop", ""), ha2]
        return secrets.compare_digest(_md5(":".join(parts)), f.get("response", "")), challenge

    def _job(s: SimStatus) -> dict[str, Any]:
        progress = s.progress if s.progress is not None else (1.0 if s.state == "done" else 0.0)
        return {
            "id": ids["current"],
            "state": {"running": "PRINTING", "done": "FINISHED"}.get(s.state, "STOPPED"),
            "progress": round(progress * 100, 1),
            "time_printing": s.seconds or 0,
            "file": {
                "name": f"{s.job}.gcode",
                "display_name": f"{s.job}.gcode",
                "path": "/usb",
                "m_timestamp": 0,
            },
        }

    def status(_: re.Match[str], __: object) -> Answer:
        s = machine.status()
        out: dict[str, Any] = {
            "printer": {"state": PRINTER_STATE[s.state], "temp_nozzle": 215.0, "temp_bed": 60.0}
        }
        if s.job is not None:
            out["job"] = {
                k: v for k, v in _job(s).items() if k in ("id", "progress", "time_printing")
            }
        return 200, out

    def job(_: re.Match[str], __: object) -> Answer:
        s = machine.status()
        return (204, None) if s.job is None else (200, _job(s))

    def print_file(m: re.Match[str], _: object) -> Answer:
        name = m.group(2)
        if not name.endswith(".gcode") or name[:-6] not in machine.files:
            return 404, {"title": "Not found"}
        try:
            machine.start(name[:-6])
        except SimRefused as e:
            return 409, {"title": "Conflict", "message": str(e)}
        ids["current"] = ids["next"]
        ids["next"] += 1
        return 204, None

    def stop(m: re.Match[str], _: object) -> Answer:
        if int(m.group(1)) != ids["current"]:
            return 404, {"title": "Not found"}
        try:
            machine.stop()
        except SimRefused as e:
            return 409, {"title": "Conflict", "message": str(e)}
        return 204, None

    routes = [
        Route("GET", r"/api/v1/status", status),
        Route("GET", r"/api/v1/job", job),
        Route("POST", r"/api/v1/files/(usb|local)/([^/]+)", print_file),
        Route("DELETE", r"/api/v1/job/(\d+)", stop),
    ]
    return serve(machine, host, port, routes, authorised)
