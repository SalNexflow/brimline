"""Running the simulated shop floor inside the engine (M12): the six mock servers, their adapters, a
watcher thread that records dispatched work the machines finish or fail, and a connectivity thread that
polls every machine's status (M12b). Two threads, so a machine that stops answering never delays the
watcher."""

import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime

from psycopg_pool import ConnectionPool

from brimline_engine.demo_clock import shop_time
from brimline_engine.dispatch.service import Shop, poll_once
from brimline_engine.machines import connectivity
from brimline_engine.machines.config import MachinesConfig, machines_config
from brimline_engine.machines.fleet import Fleet, start_fleet
from brimline_engine.settings import get_settings
from brimline_engine.shop_config import load_shop_config

log = logging.getLogger(__name__)


@dataclass
class Floor:
    fleet: Fleet
    shop: Shop
    stop: threading.Event
    watcher: threading.Thread | None
    poller: threading.Thread | None = None
    probes: ThreadPoolExecutor = field(default_factory=lambda: ThreadPoolExecutor(max_workers=8))

    def close(self) -> None:
        self.stop.set()
        for t in (self.watcher, self.poller):
            if t is not None:
                t.join(timeout=10)
        self.probes.shutdown(wait=False, cancel_futures=True)
        self.fleet.stop()


def shop_for(fleet: Fleet) -> Shop:
    return Shop(
        adapters=dict(fleet.adapters),
        prepare=lambda code, job, seconds: fleet.sims[code].prepare(job, seconds),
        speed=fleet.config.sim.speed,
        sim_seconds=lambda code: fleet.sims[code].status().seconds,
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
    settings = get_settings()
    tz = load_shop_config().shop.time_zone

    def shop_clock() -> datetime:
        return shop_time(datetime.now(UTC), settings.demo_clock, tz)

    if watch and pool is not None:

        def loop() -> None:
            while not stop.wait(cfg.sim.poll_seconds):
                try:
                    with pool.connection() as conn:
                        poll_once(conn, shop, shop_clock())
                except Exception:  # keep watching; the next round tries again
                    log.exception("dispatch watcher round failed")

        watcher = threading.Thread(target=loop, name="dispatch-watcher", daemon=True)
        watcher.start()
    floor = Floor(fleet, shop, stop, watcher)
    if watch and pool is not None:
        conn_cfg = connectivity.connectivity_config()
        interval = conn_cfg.demo_poll_seconds if settings.demo_mode else conn_cfg.poll_seconds

        def poll_round() -> None:
            # Real time: a poll is a record, not part of the plan (the demo clock is not used).
            with pool.connection() as conn:
                connectivity.poll_round(
                    conn, shop.adapters, datetime.now(UTC), conn_cfg, floor.probes
                )

        floor.poller = threading.Thread(
            target=connectivity.run_loop,
            args=(stop, interval, poll_round),
            name="connectivity-poller",
            daemon=True,
        )
        floor.poller.start()
    return floor
