from brimline_engine.scheduling.config import load_scheduler_config
from brimline_engine.scheduling.durations import eligible_machines
from brimline_engine.scheduling.generator import generate
from brimline_engine.shop_config import load_shop_config

SHOP = load_shop_config()
CFG = load_scheduler_config()


def test_the_same_seed_gives_the_same_instance() -> None:
    assert generate(3, 40, SHOP, CFG) == generate(3, 40, SHOP, CFG)
    assert generate(3, 40, SHOP, CFG) != generate(4, 40, SHOP, CFG)


def test_every_job_has_a_machine_and_sane_values() -> None:
    inst = generate(1, 80, SHOP, CFG)
    assert len(inst.jobs) == 80
    assert {m.code for m in inst.machines} == {
        "FDM-1",
        "FDM-2",
        "FDM-3",
        "FDM-4",
        "RESIN-1",
        "CNC-1",
    }
    for job in inst.jobs:
        assert eligible_machines(job, inst.machines), job.id
        assert 0 <= job.release < job.due <= inst.horizon
        assert job.quantity >= 1 and job.minutes_per_part >= 1


def test_the_mix_contains_the_hard_cases() -> None:
    jobs = generate(2, 80, SHOP, CFG).jobs
    assert any(j.rush for j in jobs)
    assert any(j.release > 0 for j in jobs)
    assert any(j.post_minutes_per_part > 0 for j in jobs)
    assert {j.process for j in jobs} == {"fdm", "resin", "cnc"}
    assert any(max(j.part_mm) > 256 for j in jobs)  # only the large printer takes these
