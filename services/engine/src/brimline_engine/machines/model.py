"""What every adapter offers, whatever its protocol.

States are Brimline's own, mapped from each protocol's words by its adapter:
  idle     ready for a new job
  running  printing or machining (ours or not: `job` says which)
  done     the last job finished and nobody has started another
  failed   the last job stopped with an error
  offline  the machine answered that it cannot work (not connected, alarm)
A machine that does not answer at all raises AdapterError("timeout"), it has no state.

`message` is the machine's own text. It is untrusted data: shown labelled, never used to decide anything.
"""

from dataclasses import dataclass
from typing import Literal, Protocol

MachineState = Literal["idle", "running", "done", "failed", "offline"]
ErrorKind = Literal["timeout", "refused", "unsupported", "protocol"]


class AdapterError(Exception):
    def __init__(self, kind: ErrorKind, detail: str) -> None:
        super().__init__(f"{kind}: {detail}")
        self.kind: ErrorKind = kind
        self.detail = detail


@dataclass(frozen=True)
class Status:
    state: MachineState
    job: str | None  # the job file the machine names, without extension (ours look like BL-0001-2)
    progress: float | None  # 0 to 1, when the protocol reports it
    seconds: int | None  # the machine's own count of seconds spent on the job
    message: str  # untrusted


class Adapter(Protocol):
    code: str
    protocol: str
    can_stop: bool  # the protocol has a call that stops a running job
    reports_job: bool  # status names the running job and says when it is done

    def get_status(self) -> Status: ...

    def start(self, job: str) -> None:
        """Start printing the file prepared for `job` (`<job>.gcode`, or the protocol's form)."""

    def stop(self, job: str) -> None: ...

    def last_error(self) -> str:
        """The machine's latest error text, or "" (untrusted)."""
