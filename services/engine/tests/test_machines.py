"""Each machine's adapter against its protocol mock (M12), in every mode: success, failure, slow and
unresponsive, plus a machine busy with someone else's work and wrong credentials.

All simulated. What a protocol cannot tell (GRBL and Formlabs have no notion of "done") is stated per case.
"""

import time
from collections.abc import Iterator

import pytest

from brimline_engine.machines.config import MachineConfig, machines_config
from brimline_engine.machines.fleet import ADAPTERS, Fleet, start_fleet
from brimline_engine.machines.model import AdapterError

CODES = ["FDM-1", "FDM-2", "FDM-3", "FDM-4", "RESIN-1", "CNC-1"]
REPORTS_DONE = {
    "FDM-1",
    "FDM-2",
    "FDM-3",
    "FDM-4",
}  # GRBL and the Formlabs Local API go back to idle
REPORTS_JOB = {"FDM-1", "FDM-2", "FDM-3", "FDM-4"}
TIMEOUT = 0.8


@pytest.fixture(scope="module")
def fleet() -> Iterator[Fleet]:
    cfg = machines_config()
    f = start_fleet(cfg.model_copy(update={"sim": cfg.sim.model_copy(update={"slow_delay_seconds": 0.3})}),
                    free_ports=True, timeout=TIMEOUT)  # fmt: skip
    yield f
    f.stop()


@pytest.fixture(autouse=True)
def fresh(fleet: Fleet) -> None:
    for sim in fleet.sims.values():
        sim.mode, sim.external_job, sim.message = "success", None, ""
        sim.speed = 600.0
        sim._job, sim._outcome, sim._error, sim._last, sim._last_seconds = (
            None,
            "idle",
            "",
            None,
            None,
        )
        sim.files.clear()


def wait_for(check: object, seconds: float = 3.0) -> bool:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if check():  # type: ignore[operator]
            return True
        time.sleep(0.05)
    return False


@pytest.mark.parametrize("code", CODES)
def test_a_job_starts_runs_and_finishes(fleet: Fleet, code: str) -> None:
    a, sim = fleet.adapters[code], fleet.sims[code]
    assert a.get_status().state == "idle"
    sim.prepare("BL-0001-2", 120)  # 120 machine seconds at 600x: 0.2 s
    sim.speed = 60.0  # 2 s, so it is still running when we look
    a.start("BL-0001-2")
    running = a.get_status()
    assert running.state == "running"
    if code in REPORTS_JOB:
        assert running.job == "BL-0001-2"
    sim.speed = 6000.0  # let it finish
    expected = "done" if code in REPORTS_DONE else "idle"
    assert wait_for(lambda: a.get_status().state == expected), a.get_status()


@pytest.mark.parametrize("code", [c for c in CODES if c != "RESIN-1"])
def test_a_running_job_can_be_stopped(fleet: Fleet, code: str) -> None:
    a, sim = fleet.adapters[code], fleet.sims[code]
    sim.prepare("BL-0003-1", 10_000)
    a.start("BL-0003-1")
    a.stop("BL-0003-1")
    assert sim.status().state == "failed"  # the controller recorded a cancelled job
    assert a.get_status().state in ("failed", "idle")


def test_the_resin_printer_cannot_be_stopped_through_its_api(fleet: Fleet) -> None:
    sim = fleet.sims["RESIN-1"]
    sim.prepare("BL-0003-1", 10_000)
    fleet.adapters["RESIN-1"].start("BL-0003-1")
    with pytest.raises(AdapterError) as e:
        fleet.adapters["RESIN-1"].stop("BL-0003-1")
    assert e.value.kind == "unsupported"
    assert sim.status().state == "running"


@pytest.mark.parametrize("code", CODES)
def test_a_failing_controller_refuses_the_start(fleet: Fleet, code: str) -> None:
    sim = fleet.sims[code]
    sim.prepare("BL-0001-2", 60)
    sim.mode = "failure"
    with pytest.raises(AdapterError) as e:
        fleet.adapters[code].start("BL-0001-2")
    assert e.value.kind == "refused"
    assert sim.status().state == "idle"


@pytest.mark.parametrize("code", CODES)
def test_a_busy_machine_refuses_the_start_and_says_it_is_running(fleet: Fleet, code: str) -> None:
    sim = fleet.sims[code]
    sim.prepare("BL-0001-2", 60)
    sim.external_job = "someone-elses-job"
    assert fleet.adapters[code].get_status().state == "running"
    with pytest.raises(AdapterError):
        fleet.adapters[code].start("BL-0001-2")


@pytest.mark.parametrize("code", CODES)
def test_a_slow_machine_still_answers_within_the_timeout(fleet: Fleet, code: str) -> None:
    fleet.sims[code].mode = "slow"
    began = time.monotonic()
    assert fleet.adapters[code].get_status().state == "idle"
    assert time.monotonic() - began >= 0.25  # 0.3 s late, less the clock's coarse ticks on Windows


@pytest.mark.parametrize("code", CODES)
def test_an_unresponsive_machine_times_out(fleet: Fleet, code: str) -> None:
    fleet.sims[code].mode = "unresponsive"
    began = time.monotonic()
    with pytest.raises(AdapterError) as e:
        fleet.adapters[code].get_status()
    assert e.value.kind == "timeout"
    assert time.monotonic() - began < TIMEOUT * 4


@pytest.mark.parametrize(
    ("code", "field", "value"),
    [
        ("FDM-1", "api_key", "wrong"),
        ("FDM-3", "password", "wrong"),
        ("FDM-4", "access_code", "wrong"),
    ],
)
def test_wrong_credentials_are_refused(fleet: Fleet, code: str, field: str, value: str) -> None:
    cfg = replace_cfg(code, field, value)
    port = fleet.servers[code].port
    adapter = ADAPTERS[cfg.protocol](cfg, fleet.config.sim.host, port, TIMEOUT)
    with pytest.raises(AdapterError):
        adapter.get_status()


def replace_cfg(code: str, field: str, value: str) -> MachineConfig:
    return machines_config().by_code()[code].model_copy(update={field: value})
