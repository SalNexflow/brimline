"""Adapters for the three REST machines: OctoPrint (FDM-1), PrusaLink (FDM-3), Formlabs Local API (RESIN-1).
The calls are the documented ones (docs/DECISIONS.md D161, D163, D165)."""

from typing import Any

import httpx2 as httpx

from brimline_engine.machines.config import MachineConfig
from brimline_engine.machines.model import AdapterError, Status


def _call(
    client: httpx.Client, method: str, path: str, json: object | None = None
) -> httpx.Response:
    try:
        return client.request(method, path, json=json)
    except httpx.TimeoutException as e:
        raise AdapterError("timeout", f"no answer to {method} {path}") from e
    except httpx.HTTPError as e:
        raise AdapterError("protocol", f"{method} {path}: {type(e).__name__}") from e


def _json(r: httpx.Response) -> Any:  # noqa: ANN401 - JSON
    try:
        return r.json()
    except ValueError as e:
        raise AdapterError("protocol", f"{r.request.method} {r.request.url.path}: not JSON") from e


class OctoPrint:
    protocol = "octoprint"
    can_stop = True
    reports_job = True

    def __init__(self, cfg: MachineConfig, host: str, port: int, timeout: float) -> None:
        self.code = cfg.code
        self._client = httpx.Client(
            base_url=f"http://{host}:{port}",
            headers={"X-Api-Key": cfg.api_key or ""},
            timeout=timeout,
        )

    def _job(self) -> dict[str, Any]:
        r = _call(self._client, "GET", "/api/job")
        if r.status_code != 200:
            raise AdapterError("protocol", f"GET /api/job answered {r.status_code}")
        body: dict[str, Any] = _json(r)
        return body

    def get_status(self) -> Status:
        j = self._job()
        text = str(j.get("state") or "")
        progress = (j.get("progress") or {}).get("completion")
        name = ((j.get("job") or {}).get("file") or {}).get("name")
        if text in ("Printing", "Pausing", "Paused", "Cancelling", "Starting"):
            state = "running"
        elif text.startswith("Error") or text == "Offline after error":
            state = "failed"
        elif text.startswith("Offline") or text == "Closed":
            state = "offline"
        else:  # Operational
            state = "done" if progress == 100 else "idle"
        return Status(
            state=state,  # type: ignore[arg-type]
            job=name.removesuffix(".gcode") if name else None,
            progress=None if progress is None else progress / 100,
            seconds=(j.get("progress") or {}).get("printTime"),
            message=str(j.get("error") or ""),
        )

    def start(self, job: str) -> None:
        r = _call(
            self._client,
            "POST",
            f"/api/files/local/{job}.gcode",
            json={"command": "select", "print": True},
        )
        if r.status_code not in (200, 204):
            raise AdapterError("refused", f"OctoPrint answered {r.status_code}")

    def stop(self, job: str) -> None:
        r = _call(self._client, "POST", "/api/job", json={"command": "cancel"})
        if r.status_code != 204:
            raise AdapterError("refused", f"OctoPrint answered {r.status_code}")

    def last_error(self) -> str:
        return str(self._job().get("error") or "")


PRUSA_STATE = {
    "IDLE": "idle",
    "READY": "idle",
    "PRINTING": "running",
    "PAUSED": "running",
    "BUSY": "running",
    "FINISHED": "done",
    "STOPPED": "failed",
    "ERROR": "failed",
    "ATTENTION": "offline",
}


class PrusaLink:
    protocol = "prusalink"
    can_stop = True
    reports_job = True

    def __init__(self, cfg: MachineConfig, host: str, port: int, timeout: float) -> None:
        self.code = cfg.code
        self._client = httpx.Client(
            base_url=f"http://{host}:{port}",
            auth=httpx.DigestAuth(cfg.username or "", cfg.password or ""),
            timeout=timeout,
        )

    def _current_job(self) -> dict[str, Any] | None:
        r = _call(self._client, "GET", "/api/v1/job")
        if r.status_code == 204:
            return None
        if r.status_code != 200:
            raise AdapterError("protocol", f"GET /api/v1/job answered {r.status_code}")
        body: dict[str, Any] = _json(r)
        return body

    def get_status(self) -> Status:
        r = _call(self._client, "GET", "/api/v1/status")
        if r.status_code != 200:
            raise AdapterError("protocol", f"GET /api/v1/status answered {r.status_code}")
        s = _json(r)
        job = self._current_job()
        name = ((job or {}).get("file") or {}).get("name")
        progress = (s.get("job") or {}).get("progress")
        return Status(
            state=PRUSA_STATE.get(str((s.get("printer") or {}).get("state")), "offline"),  # type: ignore[arg-type]
            job=name.removesuffix(".gcode") if name else None,
            progress=None if progress is None else progress / 100,
            seconds=(s.get("job") or {}).get("time_printing"),
            message="",
        )

    def start(self, job: str) -> None:
        r = _call(self._client, "POST", f"/api/v1/files/usb/{job}.gcode")
        if r.status_code != 204:
            raise AdapterError("refused", f"PrusaLink answered {r.status_code}")

    def stop(self, job: str) -> None:
        current = self._current_job()
        if (
            current is None
            or ((current.get("file") or {}).get("name") or "").removesuffix(".gcode") != job
        ):
            raise AdapterError("refused", "that job is not the printer's current job")
        r = _call(self._client, "DELETE", f"/api/v1/job/{int(current['id'])}")
        if r.status_code != 204:
            raise AdapterError("refused", f"PrusaLink answered {r.status_code}")

    def last_error(self) -> str:
        return ""


FORMLABS_STATE = {"IDLE": "idle", "PRINTING": "running", "ERROR": "failed"}


class Formlabs:
    """Through PreForm Server. No cancel and no print progress exist in the Local API (D165)."""

    protocol = "formlabs"
    can_stop = False
    reports_job = False  # no job names or "done": idle again means finished

    def __init__(self, cfg: MachineConfig, host: str, port: int, timeout: float) -> None:
        self.code = cfg.code
        self._printer = cfg.printer or ""
        self._client = httpx.Client(base_url=f"http://{host}:{port}", timeout=timeout)

    def get_status(self) -> Status:
        r = _call(self._client, "GET", f"/devices/{self._printer}/")
        if r.status_code != 200:
            raise AdapterError("protocol", f"GET /devices/ answered {r.status_code}")
        d = _json(r)
        state = (
            FORMLABS_STATE.get(str(d.get("status")), "offline")
            if d.get("is_connected")
            else "offline"
        )
        return Status(state=state, job=None, progress=None, seconds=None, message="")  # type: ignore[arg-type]

    def start(self, job: str) -> None:
        r = _call(
            self._client, "POST", "/load-form/", json={"file": f"C:/Brimline/jobs/{job}.form"}
        )
        if r.status_code not in (200, 202):
            raise AdapterError("refused", f"load-form answered {r.status_code}")
        scene = _json(r).get("id")
        body = {"printer": self._printer, "job_name": job, "print_now": True}
        r = _call(self._client, "POST", f"/scene/{scene}/print/", json=body)
        if r.status_code not in (200, 202):
            raise AdapterError("refused", f"print answered {r.status_code}")

    def stop(self, job: str) -> None:
        raise AdapterError("unsupported", "the Formlabs Local API has no call that cancels a print")

    def last_error(self) -> str:
        return ""
