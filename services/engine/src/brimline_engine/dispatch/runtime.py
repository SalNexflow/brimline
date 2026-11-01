"""Running the simulated shop floor inside the engine (M12): the six mock servers, their adapters, and a
watcher thread that records dispatched work the machines finish or fail."""

import logging
import threading
from dataclasses import dataclass
from datetime import UTC, datetime

from psycopg_pool import ConnectionPool

from brimline_engine.dispatch.service import Shop, poll_once
from brimline_engine.machines.config import MachinesConfig, machines_config
from brimline_engine.machines.fleet import Fleet, start_fleet

log = logging.getLogger(__name__)


@dataclass
class Floor:
    fleet: Fleet
    shop: Shop
    stop: threading.Event
    watcher: threading.Thread | None

    def close(self) -> None:
        self.stop.set()
        if self.watcher is not None:
            self.watcher.join(timeout=10)
        self.fleet.stop()


def shop_for(fleet: Fleet) -> Shop:
    return Shop(
        adapters=dict(fleet.adapters),
        prepare=lambda code, job, seconds: fleet.sims[code].prepare(job, seconds),
        speed=fleet.config.sim.speed,
    )


def sources(cfg: MachinesConfig | None = None) -> dict[str, str]:
    return {m.code: m.source for m in (cfg or machines_config()).machines}


def open_floor(
    pool: ConnectionPool | None,
    *,
    free_ports: bool = False,
    watch: bool = True,
    timeout: float | None = None,
) -> Floor:
    cfg = machines_config()
    fleet = start_fleet(cfg, free_ports=free_ports, timeout=timeout)
    shop = shop_for(fleet)
    stop = threading.Event()
    watcher = None
    if watch and pool is not None:

        def loop() -> None:
            while not stop.wait(cfg.sim.poll_seconds):
                try:
                    with pool.connection() as conn:
                        poll_once(conn, shop, datetime.now(UTC))
                except Exception:  # keep watching; the next round tries again
                    log.exception("dispatch watcher round failed")

        watcher = threading.Thread(target=loop, name="dispatch-watcher", daemon=True)
        watcher.start()
    return Floor(fleet, shop, stop, watcher)
