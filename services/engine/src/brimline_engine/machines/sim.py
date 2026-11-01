"""The simulated controller behind every mock server: one per machine, protocol-free.

Each mock server translates its protocol's requests into calls here and the answers back into its protocol's
replies, so all six machines behave alike and differ only in how they are spoken to.

Time: a job runs `seconds / speed` real seconds (config/machines.toml `[sim] speed`), and the machine reports
the simulated seconds it has spent, as a real controller reports its print time.

Modes (set per machine, for tests, the eval and the demo):
  success       starts, runs and finishes
  failure       refuses every start with an error
  slow          answers every request `slow_delay_seconds` late
  unresponsive  accepts connections but never answers
"""

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal

Mode = Literal["success", "failure", "slow", "unresponsive"]
SimState = Literal["idle", "running", "done", "failed", "offline"]


class SimRefused(Exception):  # noqa: N818 - reads as "the controller refused"
    """The controller refuses the request (busy, unknown file, failure mode, nothing to stop)."""


@dataclass(frozen=True)
class SimStatus:
    state: SimState
    job: str | None
    progress: float | None
    seconds: int | None
    message: str


@dataclass
class SimMachine:
    code: str
    speed: float
    slow_delay: float
    clock: Callable[[], float] = time.monotonic
    mode: Mode = "success"
    external_job: str | None = None  # printing something Brimline did not start
    message: str = ""  # free text the machine reports (untrusted)
    files: dict[str, int] = field(default_factory=dict)  # job -> simulated machine seconds
    _job: str | None = None
    _started: float = 0.0
    _outcome: SimState = "idle"
    _error: str = ""
    _last: str | None = None  # the job that finished or was stopped last
    _last_seconds: int | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock)

    # --- set-up, outside any protocol --------------------------------------------------------------

    def prepare(self, job: str, seconds: int) -> None:
        """A sliced file for `job` is on the machine (stands in for the upload a shop would do)."""
        with self._lock:
            self.files[job] = max(1, seconds)

    def fail_running(self, error: str) -> None:
        """The running job fails now with this error (tests; a demo switch)."""
        with self._lock:
            if self._job is not None:
                self._job = None
                self._outcome = "failed"
                self._error = error

    # --- what every protocol asks ------------------------------------------------------------------

    def delay(self) -> float | None:
        """Seconds to wait before answering, or None for never (unresponsive)."""
        if self.mode == "unresponsive":
            return None
        return self.slow_delay if self.mode == "slow" else 0.0

    def status(self) -> SimStatus:
        with self._lock:
            self._settle()
            if self.external_job is not None:
                return SimStatus("running", self.external_job, None, None, self.message)
            if self._job is not None:
                total = self.files[self._job]
                done = min(total, int((self.clock() - self._started) * self.speed))
                return SimStatus("running", self._job, done / total, done, self.message)
            if self._outcome == "failed":
                return SimStatus("failed", None, None, None, self._error or self.message)
            return SimStatus(self._outcome, self._last, None, self._last_seconds, self.message)

    def start(self, job: str) -> None:
        with self._lock:
            self._settle()
            if self.mode == "failure":
                raise SimRefused("the controller refused to start (simulated failure)")
            if self.external_job is not None or self._job is not None:
                raise SimRefused("busy")
            if job not in self.files:
                raise SimRefused(f"no file for {job}")
            self._job, self._started, self._outcome, self._error = job, self.clock(), "running", ""

    def stop(self) -> None:
        with self._lock:
            self._settle()
            if self._job is None:
                raise SimRefused("nothing is running")
            self._last, self._last_seconds = (
                self._job,
                int((self.clock() - self._started) * self.speed),
            )
            self._job, self._outcome, self._error = None, "failed", "cancelled by the operator"

    def last_error(self) -> str:
        with self._lock:
            return self._error

    # --- internals ---------------------------------------------------------------------------------

    def _settle(self) -> None:
        """A running job whose time is up has finished."""
        if self._job is None:
            return
        total = self.files[self._job]
        if (self.clock() - self._started) * self.speed >= total:
            self._last, self._last_seconds = self._job, total
            self._job, self._outcome = None, "done"


def wait_or_hang(machine: SimMachine, stop: threading.Event) -> bool:
    """Sleep as the mode says before answering. False: never answer (the caller drops the request,
    keeping the connection open until the server stops)."""
    d = machine.delay()
    if d is None:
        stop.wait()
        return False
    if d:
        time.sleep(d)
    return True
