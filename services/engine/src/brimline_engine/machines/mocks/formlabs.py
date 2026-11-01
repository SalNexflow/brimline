"""The Formlabs Local API (PreForm Server), as documented (docs/DECISIONS.md D165), for one simulated
printer. It has no call that cancels a print or reports a print's progress; neither does this mock.
The device status strings (IDLE, PRINTING, ERROR) are assumed: the documentation does not list them."""

import itertools
import re

from brimline_engine.machines.config import MachineConfig
from brimline_engine.machines.mocks.http import Answer, Route, Running, serve
from brimline_engine.machines.sim import SimMachine, SimRefused

STATUS = {
    "idle": "IDLE",
    "done": "IDLE",
    "running": "PRINTING",
    "failed": "ERROR",
    "offline": "OFFLINE",
}


def start(machine: SimMachine, cfg: MachineConfig, host: str, port: int) -> Running:
    scenes: dict[str, str] = {}  # scene id -> job
    ids = itertools.count(1)

    def device(m: re.Match[str], _: object) -> Answer:
        if m.group(1) != cfg.printer:
            return 404, {"error": "device not found"}
        s = machine.status()
        return 200, {
            "id": cfg.printer,
            "product_name": "Form 4",
            "status": STATUS[s.state],
            "is_connected": s.state != "offline",
            "connection_type": "WIFI",
            "ip_address": host,
            "firmware_version": "sim",
        }

    def load_form(_: re.Match[str], body: object) -> Answer:
        path = body.get("file") if isinstance(body, dict) else None
        job = str(path or "").replace("\\", "/").rsplit("/", 1)[-1].removesuffix(".form")
        if job not in machine.files:
            return 400, {"error": f"cannot load {path!r}"}
        scene = f"scene-{next(ids)}"
        scenes[scene] = job
        return 200, {"id": scene, "models": [], "layer_count": 0}

    def send(m: re.Match[str], body: object) -> Answer:
        job = scenes.get(m.group(1))
        if job is None:
            return 400, {"error": "unknown scene"}
        if (
            not isinstance(body, dict)
            or body.get("printer") != cfg.printer
            or not body.get("job_name")
        ):
            return 400, {"error": "printer and job_name are required"}
        try:
            machine.start(job)
        except SimRefused as e:
            return 400, {"error": str(e)}
        return 200, {"job_id": f"{job}-{m.group(1)}"}

    routes = [
        Route("GET", r"/devices/([^/]+)/", device),
        Route("POST", r"/load-form/", load_form),
        Route("POST", r"/scene/([^/]+)/print/", send),
    ]
    return serve(machine, host, port, routes, lambda _: (True, {}))
