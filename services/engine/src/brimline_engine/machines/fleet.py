"""The simulated shop floor: one simulated controller and one protocol mock server per machine, and an
adapter per machine pointed at its mock. Started by the engine when SIM_MACHINES is on (the demo, dev) and
by tests (on free ports)."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from brimline_engine.machines.adapters.http_based import Formlabs, OctoPrint, PrusaLink
from brimline_engine.machines.adapters.streaming import Bambu, Grbl, Moonraker
from brimline_engine.machines.config import MachineConfig, MachinesConfig
from brimline_engine.machines.mocks import bambu, formlabs, grbl, moonraker, octoprint, prusalink
from brimline_engine.machines.model import Adapter
from brimline_engine.machines.sim import SimMachine


class _Server(Protocol):
    @property
    def port(self) -> int: ...

    def stop(self) -> None: ...


MOCKS: dict[str, Callable[[SimMachine, MachineConfig, str, int], Any]] = {
    "octoprint": octoprint.start,
    "moonraker": moonraker.start,
    "prusalink": prusalink.start,
    "bambu": bambu.start,
    "formlabs": formlabs.start,
    "grbl": grbl.start,
}
ADAPTERS: dict[str, Callable[[MachineConfig, str, int, float], Adapter]] = {
    "octoprint": OctoPrint,
    "moonraker": Moonraker,
    "prusalink": PrusaLink,
    "bambu": Bambu,
    "formlabs": Formlabs,
    "grbl": Grbl,
}


@dataclass
class Fleet:
    config: MachinesConfig
    sims: dict[str, SimMachine]
    adapters: dict[str, Adapter]
    servers: dict[str, _Server]

    def stop(self) -> None:
        for s in self.servers.values():
            s.stop()


def start_fleet(
    cfg: MachinesConfig, *, free_ports: bool = False, timeout: float | None = None
) -> Fleet:
    """Start every mock server and connect an adapter to it. `free_ports`: let the system pick ports
    (tests run next to a dev engine)."""
    sims, adapters, servers = {}, {}, {}
    host = cfg.sim.host
    try:
        for m in cfg.machines:
            sim = SimMachine(m.code, cfg.sim.speed, cfg.sim.slow_delay_seconds)
            server = MOCKS[m.protocol](sim, m, host, 0 if free_ports else m.port)
            sims[m.code], servers[m.code] = sim, server
            adapters[m.code] = ADAPTERS[m.protocol](
                m, host, server.port, timeout or cfg.sim.timeout_seconds
            )
    except Exception:
        for s in servers.values():
            s.stop()
        raise
    return Fleet(cfg, sims, adapters, servers)
