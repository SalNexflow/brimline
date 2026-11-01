"""Shortages and purchase suggestions (M9), worked out by hand.

Windows: Monday [0, 540), Tuesday [1440, 1980) (08:00-17:00), as in the shop's calendar.
"""

from datetime import UTC, date, datetime, time

from brimline_engine.materials.config import Supply
from brimline_engine.materials.shortage import Need, Shortage, need_time, shortages, suggest

WINDOWS = ((0, 540), (1440, 1980))
TZ = "Europe/Berlin"
TEN = time(10, 0)


def test_need_time_works_back_from_the_due_time() -> None:
    # Due Tue 17:00 (1980). Finish 12 min -> starts 1968. Machine 200 -> starts by 1768 (Tue).
    assert need_time({"prep": 15, "machine": 200, "finish": 12}, 1980, WINDOWS, 0) == 1768


def test_need_time_includes_post_processing() -> None:
    # Finish 1968-1980, post 24 min -> 1944, machine 200 -> 1744.
    d = {"prep": 15, "machine": 200, "post": 24, "finish": 12}
    assert need_time(d, 1980, WINDOWS, 0) == 1744


def test_a_machine_task_may_start_the_day_before_and_run_overnight() -> None:
    # Due Tue 1500: finish 1488-1500; the machine must end by 1488, so start by 1288. No shift
    # holds 1288; the latest machine start before it is Monday's last minute, 539.
    assert need_time({"machine": 200, "finish": 12}, 1500, WINDOWS, 0) == 539


def test_need_time_is_now_when_on_time_is_already_impossible() -> None:
    assert need_time({"machine": 200, "finish": 12}, 100, WINDOWS, 30) == 30
    # Possible, but earlier than now: now.
    assert need_time({"machine": 100, "finish": 12}, 400, WINDOWS, 300) == 300


def test_runs_short_at_the_first_uncovered_need() -> None:
    # Stock 500: A 300 at 100 -> 200; B 300 at 200 -> -100 (short); delivery 1000 at 300 -> 900;
    # C 300 at 400 -> 600. Short at 200 by 100 g; only B is affected.
    needs = [Need("A", "TPU", 300, 100), Need("B", "TPU", 300, 200), Need("C", "TPU", 300, 400)]
    assert shortages({"TPU": 500}, [("TPU", 300, 1000)], needs) == [
        Shortage("TPU", 200, 100, ("B",))
    ]


def test_a_delivery_at_the_need_minute_comes_first() -> None:
    needs = [Need("A", "TPU", 300, 200)]
    assert shortages({"TPU": 0}, [("TPU", 200, 300)], needs) == []
    assert shortages({"TPU": 0}, [("TPU", 201, 300)], needs) == [Shortage("TPU", 200, 300, ("A",))]


def test_two_dips_give_the_lowest_level() -> None:
    # 100 - 200 = -100 (A), + 150 = 50, - 100 = -50 (B): short at 10 by 100, A and B affected.
    needs = [Need("A", "PLA", 200, 10), Need("B", "PLA", 100, 30)]
    assert shortages({"PLA": 100}, [("PLA", 20, 150)], needs) == [
        Shortage("PLA", 10, 100, ("A", "B"))
    ]


def test_materials_are_independent_and_unlisted_stock_is_zero() -> None:
    needs = [Need("A", "PLA", 10, 5), Need("B", "PETG", 10, 5)]
    assert shortages({"PLA": 10}, [], needs) == [Shortage("PETG", 5, 10, ("B",))]


TPU = Supply(supplier="S", lead_time_days=2, pack_grams=500, safety_stock_g=0)


def test_suggestion_in_time() -> None:
    # Needed Thu 29 Oct 08:15 Berlin (07:15 UTC). Ordered Tue 27 it arrives Thu 10:00, too
    # late, so the latest day is Mon 26. Today is Mon 26: in time, arrives Wed 28 10:00
    # (09:00 UTC). 160 g short -> one 500 g pack.
    o = suggest(160, datetime(2026, 10, 29, 7, 15, tzinfo=UTC), TPU, TEN, TZ,
                now=datetime(2026, 10, 26, 9, 0, tzinfo=UTC))  # fmt: skip
    assert (o.grams, o.packs, o.order_by, o.in_time) == (500, 1, date(2026, 10, 26), True)
    assert o.arrives_at == datetime(2026, 10, 28, 9, 0, tzinfo=UTC)


def test_suggestion_too_late_says_order_today() -> None:
    o = suggest(160, datetime(2026, 10, 29, 7, 15, tzinfo=UTC), TPU, TEN, TZ,
                now=datetime(2026, 10, 28, 15, 0, tzinfo=UTC))  # fmt: skip
    assert (o.order_by, o.in_time) == (date(2026, 10, 28), False)
    assert o.arrives_at == datetime(2026, 10, 30, 9, 0, tzinfo=UTC)  # Fri 10:00 Berlin


def test_suggestion_across_the_clock_change_uses_shop_time() -> None:
    # Clocks went back on Sun 25 Oct. Needed Mon 26 09:30 Berlin (08:30 UTC); deliveries at
    # 09:00 shop time. Ordered Sat 24 it arrives Mon 26 09:00 CET (08:00 UTC): in time. Doing
    # the sums in UTC (09:00 UTC on Monday, after 08:30) would wrongly say Friday 23.
    supply = Supply(supplier="S", lead_time_days=2, pack_grams=1000, safety_stock_g=0)
    o = suggest(10, datetime(2026, 10, 26, 8, 30, tzinfo=UTC), supply, time(9, 0), TZ,
                now=datetime(2026, 10, 20, 8, 0, tzinfo=UTC))  # fmt: skip
    assert o.order_by == date(2026, 10, 24)
    assert o.arrives_at == datetime(2026, 10, 26, 8, 0, tzinfo=UTC)


def test_whole_packs_cover_the_shortfall_and_the_safety_stock() -> None:
    # 1200 short + 500 safety = 1700 -> two 1000 g packs.
    supply = Supply(supplier="S", lead_time_days=3, pack_grams=1000, safety_stock_g=500)
    o = suggest(1200, datetime(2026, 11, 6, 12, 0, tzinfo=UTC), supply, TEN, TZ,
                now=datetime(2026, 11, 2, 8, 0, tzinfo=UTC))  # fmt: skip
    assert (o.grams, o.packs) == (2000, 2)
    # Needed Fri 6 Nov 13:00; ordered Tue 3 it arrives Fri 10:00: in time.
    assert o.order_by == date(2026, 11, 3)
