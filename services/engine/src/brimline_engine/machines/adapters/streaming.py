"""Adapters for the three non-REST machines: Moonraker websocket JSON-RPC (FDM-2), Bambu LAN MQTT (FDM-4,
community-documented), GRBL serial G-code streaming (CNC-1). See docs/DECISIONS.md D162, D164, D166."""

import itertools
import json
import threading
from typing import Any

import paho.mqtt.client as mqtt
import serial
from paho.mqtt.enums import CallbackAPIVersion
from websockets.exceptions import WebSocketException
from websockets.sync.client import connect

from brimline_engine.machines.config import MachineConfig
from brimline_engine.machines.model import AdapterError, Status

KLIPPER_STATE = {
    "standby": "idle",
    "printing": "running",
    "paused": "running",
    "complete": "done",
    "error": "failed",
    "cancelled": "failed",
}


class Moonraker:
    protocol = "moonraker"
    can_stop = True
    reports_job = True

    def __init__(self, cfg: MachineConfig, host: str, port: int, timeout: float) -> None:
        self.code = cfg.code
        self._url = f"ws://{host}:{port}/websocket"
        self._timeout = timeout
        self._ids = itertools.count(1)

    def _rpc(self, method: str, params: dict[str, Any] | None = None) -> Any:  # noqa: ANN401 - JSON
        request: dict[str, Any] = {"jsonrpc": "2.0", "method": method, "id": next(self._ids)}
        if params is not None:
            request["params"] = params
        try:
            with connect(self._url, open_timeout=self._timeout, close_timeout=1) as ws:
                ws.send(json.dumps(request))
                while True:
                    reply = json.loads(ws.recv(timeout=self._timeout))
                    if reply.get("id") == request["id"]:
                        break
        except TimeoutError as e:
            raise AdapterError("timeout", f"no answer to {method}") from e
        except (WebSocketException, OSError, json.JSONDecodeError) as e:
            raise AdapterError("protocol", f"{method}: {type(e).__name__}") from e
        if "error" in reply:
            raise AdapterError("refused", str((reply["error"] or {}).get("message", "error")))
        return reply.get("result")

    def get_status(self) -> Status:
        result = self._rpc("printer.objects.query", {"objects": {"print_stats": None}})
        stats = ((result or {}).get("status") or {}).get("print_stats") or {}
        name = str(stats.get("filename") or "")
        return Status(
            state=KLIPPER_STATE.get(str(stats.get("state")), "offline"),  # type: ignore[arg-type]
            job=name.removesuffix(".gcode") or None,
            progress=None,
            seconds=int(stats.get("print_duration") or 0) or None,
            message=str(stats.get("message") or ""),
        )

    def start(self, job: str) -> None:
        self._rpc("printer.print.start", {"filename": f"{job}.gcode"})

    def stop(self, job: str) -> None:
        self._rpc("printer.print.cancel")

    def last_error(self) -> str:
        return self.get_status().message


BAMBU_STATE = {
    "IDLE": "idle",
    "PREPARE": "running",
    "RUNNING": "running",
    "PAUSE": "running",
    "FINISH": "done",
    "FAILED": "failed",
}


class Bambu:
    """LAN mode MQTT. COMMUNITY-documented format (OpenBambuAPI), not supported by Bambu Lab (D164)."""

    protocol = "bambu"
    can_stop = True
    reports_job = True

    def __init__(self, cfg: MachineConfig, host: str, port: int, timeout: float) -> None:
        self.code = cfg.code
        self._host, self._port, self._timeout = host, port, timeout
        self._serial, self._access = cfg.serial or "", cfg.access_code or ""
        self._seq = itertools.count(1)

    def _exchange(self, request: dict[str, Any], want: str) -> dict[str, Any]:
        """Publish one request and wait for the report answering it (`want`: the command it names)."""
        seq = str(next(self._seq))
        for section in request.values():
            section["sequence_id"] = seq
        got: dict[str, Any] = {}
        connected, answered = threading.Event(), threading.Event()
        refused: list[int] = []
        client = mqtt.Client(CallbackAPIVersion.VERSION2, protocol=mqtt.MQTTv311)
        client.username_pw_set("bblp", self._access)

        def on_connect(c: mqtt.Client, _u: Any, _f: Any, rc: Any, _p: Any) -> None:  # noqa: ANN401
            if rc.is_failure:
                refused.append(int(rc.value))
            else:
                c.subscribe(f"device/{self._serial}/report")
            connected.set()

        def on_subscribe(c: mqtt.Client, *_: Any) -> None:  # noqa: ANN401
            c.publish(f"device/{self._serial}/request", json.dumps(request))

        def on_message(_c: mqtt.Client, _u: Any, msg: mqtt.MQTTMessage) -> None:  # noqa: ANN401
            try:
                body = json.loads(msg.payload)
            except json.JSONDecodeError:
                return
            p = body.get("print") if isinstance(body, dict) else None
            if isinstance(p, dict) and p.get("sequence_id") == seq and p.get("command") == want:
                got.update(p)
                answered.set()

        client.on_connect, client.on_subscribe, client.on_message = (
            on_connect,
            on_subscribe,
            on_message,
        )
        try:
            client.connect(self._host, self._port, keepalive=10)
        except OSError as e:
            raise AdapterError("protocol", f"MQTT connect: {type(e).__name__}") from e
        client.loop_start()
        try:
            if not connected.wait(self._timeout):
                raise AdapterError("timeout", "no CONNACK from the printer")
            if refused:
                raise AdapterError("refused", f"the printer refused the login (code {refused[0]})")
            if not answered.wait(self._timeout):
                raise AdapterError("timeout", f"no report answering {want}")
        finally:
            client.disconnect()
            client.loop_stop()
        return got

    def get_status(self) -> Status:
        p = self._exchange(
            {"pushing": {"command": "pushall", "version": 1, "push_target": 1}}, "push_status"
        )
        error = int(p.get("print_error") or 0)
        return Status(
            state=BAMBU_STATE.get(str(p.get("gcode_state")), "offline"),  # type: ignore[arg-type]
            job=str(p.get("subtask_name") or "") or None,
            progress=None if p.get("mc_percent") is None else int(p["mc_percent"]) / 100,
            seconds=None,
            message=f"print_error {error:#010x}" if error else "",
        )

    def start(self, job: str) -> None:
        p = self._exchange(
            {"print": {"command": "gcode_file", "param": f"{job}.gcode"}}, "gcode_file"
        )
        if p.get("result") != "success":
            raise AdapterError("refused", "the printer did not start the file")

    def stop(self, job: str) -> None:
        p = self._exchange({"print": {"command": "stop", "param": ""}}, "stop")
        if p.get("result") != "success":
            raise AdapterError("refused", "the printer did not stop")

    def last_error(self) -> str:
        return self.get_status().message


GRBL_STATE = {
    "Idle": "idle",
    "Run": "running",
    "Hold": "running",
    "Jog": "running",
    "Home": "running",
    "Alarm": "failed",
    "Door": "offline",
    "Check": "offline",
    "Sleep": "offline",
}


class Grbl:
    """Serial G-code streaming, send-response (D166), over pyserial's socket:// URL to the mock."""

    protocol = "grbl"
    can_stop = True
    reports_job = False  # no job names or "done": idle again means finished

    def __init__(self, cfg: MachineConfig, host: str, port: int, timeout: float) -> None:
        self.code = cfg.code
        self._url, self._timeout = f"socket://{host}:{port}", timeout

    def _open(self) -> serial.SerialBase:
        try:
            line = serial.serial_for_url(self._url, timeout=self._timeout)
        except (serial.SerialException, OSError) as e:
            raise AdapterError("protocol", f"serial open: {type(e).__name__}") from e
        # The welcome line may come before or after the port is open (pyserial clears what arrived
        # before), so nothing waits for it; the answers below skip it when it comes.
        return line

    def _until(self, line: serial.SerialBase, done: Any, what: str) -> list[str]:  # noqa: ANN401
        """Read lines until done(text); a silence of `timeout` seconds is a timeout."""
        seen: list[str] = []
        while True:
            raw = line.readline()
            if not raw:
                line.close()
                raise AdapterError("timeout", f"no {what} from the controller")
            text = raw.decode(errors="replace").strip()
            if text:
                seen.append(text)
                if done(text):
                    return seen

    def get_status(self) -> Status:
        line = self._open()
        try:
            line.write(b"?")
            report = self._until(line, lambda t: t.startswith("<"), "status report")[-1]
        finally:
            line.close()
        word = report[1:].split("|", 1)[0]
        state = GRBL_STATE.get(word, "offline")
        return Status(state=state, job=None, progress=None, seconds=None, message="")  # type: ignore[arg-type]

    def start(self, job: str) -> None:
        program = [f"(BRIMLINE JOB {job})", "G21", "G90", "M3 S10000", "G0 X0 Y0", "G1 X10 Y0 F500"]
        line = self._open()
        try:
            for text in program:
                line.write(text.encode() + b"\n")
                answer = self._until(line, lambda t: t == "ok" or t.startswith("error:"), "ok")[-1]
                if answer != "ok":
                    raise AdapterError("refused", f"GRBL answered {answer} to {text}")
        finally:
            line.close()

    def stop(self, job: str) -> None:
        line = self._open()
        try:
            line.write(b"!")  # feed hold, then soft reset: the documented way to abort
            line.write(b"\x18")
            self._until(line, lambda t: t.startswith("Grbl "), "reset")
            line.write(b"$X\n")  # unlock the alarm a reset in motion leaves
            self._until(line, lambda t: t == "ok" or t.startswith("error:"), "ok")
        finally:
            line.close()

    def last_error(self) -> str:
        return "alarm" if self.get_status().state == "failed" else ""
