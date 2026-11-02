import { describe, expect, it } from "vitest";

import {
  boardWindow,
  formatShopTime,
  lanes,
  materialToken,
  percentAt,
  shopLocalToUtc,
  startOfShopDay,
  utcToShopLocal,
} from "./timeline";

const TZ = "Europe/Berlin";
const at = (iso: string) => new Date(iso);

describe("startOfShopDay", () => {
  it("is local midnight in the shop's zone", () => {
    // 10:00 in Berlin on Monday 26 Oct 2026 (winter time, UTC+1): midnight is 23:00 UTC the day before.
    expect(startOfShopDay(at("2026-10-26T09:00:00Z"), TZ).toISOString()).toBe("2026-10-25T23:00:00.000Z");
  });

  it("keeps a late-evening time on its own day (review finding)", () => {
    // 23:30 in Berlin on Monday 26 Oct = 22:30 UTC: still Monday, so midnight is 25 Oct 23:00 UTC.
    expect(startOfShopDay(at("2026-10-26T22:30:00Z"), TZ).toISOString()).toBe("2026-10-25T23:00:00.000Z");
    // 23:59 likewise, and 00:00 the next day starts that day.
    expect(startOfShopDay(at("2026-10-26T22:59:00Z"), TZ).toISOString()).toBe("2026-10-25T23:00:00.000Z");
    expect(startOfShopDay(at("2026-10-26T23:00:00Z"), TZ).toISOString()).toBe("2026-10-26T23:00:00.000Z");
  });

  it("lands on 00:00 on the day the clocks go back", () => {
    // Sunday 25 Oct 2026 has 25 hours in Berlin; its midnight was still in summer time (UTC+2).
    expect(startOfShopDay(at("2026-10-25T20:00:00Z"), TZ).toISOString()).toBe("2026-10-24T22:00:00.000Z");
  });
});

describe("boardWindow", () => {
  it("covers whole days from the plan's start until the last task ends", () => {
    // Start Monday 10:00; the last task ends Wednesday 09:00 local: Mon, Tue, Wed (minimum 3 days).
    const w = boardWindow(at("2026-10-26T09:00:00Z"), [at("2026-10-28T08:00:00Z")], TZ);
    expect(w.days.map((d) => d.toISOString())).toEqual([
      "2026-10-25T23:00:00.000Z",
      "2026-10-26T23:00:00.000Z",
      "2026-10-27T23:00:00.000Z",
    ]);
    expect(w.to.toISOString()).toBe("2026-10-28T23:00:00.000Z");
  });

  it("grows to fit a task that ends days later", () => {
    const w = boardWindow(at("2026-10-26T09:00:00Z"), [at("2026-11-02T10:00:00Z")], TZ);
    expect(w.days).toHaveLength(8); // Mon 26 Oct to Mon 2 Nov
  });

  it("stops at maxDays even when work ends later", () => {
    // Mon 26 Oct 10:00 local, work until Mon 2 Nov: capped at Mon, Tue, Wed; ends Thu 29 Oct 00:00.
    const w = boardWindow(at("2026-10-26T09:00:00Z"), [at("2026-11-02T10:00:00Z")], TZ, 3, 3);
    expect(w.days).toHaveLength(3);
    expect(w.to.toISOString()).toBe("2026-10-28T23:00:00.000Z");
  });

  it("still covers a day across the autumn clock change when capped", () => {
    // Sat 24 Oct to Mon 26 Oct: Sunday 25 Oct has 25 hours in Berlin.
    const w = boardWindow(at("2026-10-24T08:00:00Z"), [at("2026-10-30T08:00:00Z")], TZ, 3, 3);
    expect(w.days.map((d) => d.toISOString())).toEqual([
      "2026-10-23T22:00:00.000Z",
      "2026-10-24T22:00:00.000Z",
      "2026-10-25T23:00:00.000Z",
    ]);
  });
});

describe("percentAt", () => {
  it("is linear in time and clamped", () => {
    const w = { from: at("2026-10-26T00:00:00Z"), to: at("2026-10-27T00:00:00Z") };
    expect(percentAt(at("2026-10-26T06:00:00Z"), w)).toBe(25);
    expect(percentAt(at("2026-10-25T06:00:00Z"), w)).toBe(0);
    expect(percentAt(at("2026-10-28T06:00:00Z"), w)).toBe(100);
  });
});

describe("lanes", () => {
  it("stacks overlapping work and reuses a lane once it is free", () => {
    const t = (s: string, e: string) => ({ start: at(`2026-10-26T${s}:00Z`), end: at(`2026-10-26T${e}:00Z`) });
    // A 08-09 and B 08:30-09:30 overlap; C 09:00-10:00 can follow A on lane 0.
    expect(lanes([t("08:00", "09:00"), t("08:30", "09:30"), t("09:00", "10:00")])).toEqual([0, 1, 0]);
  });
});

describe("materialToken", () => {
  it("gives a material the same token wherever it appears", () => {
    const codes = ["PLA-BLACK", "PETG-BLACK", "PLA-BLACK", "AL-6061"];
    expect(materialToken("PLA-BLACK", codes)).toBe("var(--bar-3)"); // AL, PETG, PLA
    expect(materialToken("AL-6061", codes)).toBe("var(--bar-1)");
  });
});

describe("formatShopTime", () => {
  it("shows shop time, not the viewer's", () => {
    expect(formatShopTime("2026-10-26T09:15:00Z", TZ)).toBe("Mon 26 Oct, 10:15");
  });
});

describe("shop time in date-time fields", () => {
  it("shows a UTC instant in shop time and reads it back", () => {
    // 16:00 UTC on Mon 26 Oct 2026 is 17:00 in Berlin (winter time).
    expect(utcToShopLocal("2026-10-26T16:00:00Z", TZ)).toBe("2026-10-26T17:00");
    expect(shopLocalToUtc("2026-10-26T17:00", TZ)).toBe("2026-10-26T16:00:00.000Z");
  });

  it("uses summer time before the change", () => {
    // 17:00 Berlin on Fri 23 Oct 2026 is UTC+2: 15:00 UTC.
    expect(shopLocalToUtc("2026-10-23T17:00", TZ)).toBe("2026-10-23T15:00:00.000Z");
  });

  it("refuses something that is not a time", () => {
    expect(shopLocalToUtc("tomorrow", TZ)).toBeNull();
  });
});
