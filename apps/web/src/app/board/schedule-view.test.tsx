import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, test } from "vitest";

import type { Schedule } from "@/lib/engine";

import { Timeline } from "./schedule-view";

afterEach(cleanup);

// A plan made by hand: a print and a prep on Monday, and a second print on Saturday, five days
// later. The timeline draws Monday to Wednesday; Saturday's print is counted on its row instead.
const TZ = "Europe/Berlin";
const job = { key: "BL-0001-1", order_number: "BL-0001", part_name: "Wheel hub", quantity: 8, material_code: "PLA-BLACK", rush: false };
const later = { ...job, key: "BL-0002-1", order_number: "BL-0002", part_name: "Sensor bracket" };
const schedule = {
  version: 7,
  plan_start: "2026-11-02T08:00:00Z", // Mon 2 Nov, 09:00 in Berlin
  machines: [{ code: "FDM-1" }],
  shifts: [],
  jobs: [job, later],
  tasks: [
    { job: "BL-0001-1", kind: "prep", machine: null, start: "2026-11-02T08:00:00Z", end: "2026-11-02T08:15:00Z", status: "planned" },
    { job: "BL-0001-1", kind: "machine", machine: "FDM-1", start: "2026-11-02T09:00:00Z", end: "2026-11-02T13:00:00Z", status: "planned" },
    { job: "BL-0002-1", kind: "machine", machine: "FDM-1", start: "2026-11-07T09:00:00Z", end: "2026-11-07T11:00:00Z", status: "planned" },
  ],
} as unknown as Schedule;
const now = new Date("2026-11-02T08:30:00Z");

test("by default three days are drawn and later work is counted on its row", () => {
  const { container } = render(<Timeline schedule={schedule} timeZone={TZ} now={now} />);
  expect(container.querySelectorAll(".day-label")).toHaveLength(3);
  expect(container.querySelectorAll(".bar")).toHaveLength(2); // Monday's prep and print
  const marker = screen.getByTestId("later-FDM-1");
  expect(marker.textContent).toBe("+1 later");
  expect(marker.getAttribute("href")).toBe("#table-7");
  expect(marker.getAttribute("aria-label")).toBe("+1 later: 1 more task on FDM-1 after Wed 4 Nov, listed in the table");
  expect(screen.queryByTestId("later-manual-0")).toBeNull();
});

test("the whole plan draws every day and marks nothing as later", () => {
  const { container } = render(<Timeline schedule={schedule} timeZone={TZ} now={now} span="all" />);
  expect(container.querySelectorAll(".day-label")).toHaveLength(6); // Mon 2 to Sat 7 Nov
  expect(container.querySelectorAll(".bar")).toHaveLength(3);
  expect(screen.queryByTestId("later-FDM-1")).toBeNull();
});

test("each bar carries its full details for the hover and focus tip", () => {
  const { container } = render(<Timeline schedule={schedule} timeZone={TZ} now={now} />);
  for (const bar of container.querySelectorAll(".bar")) {
    expect(bar.getAttribute("data-tip")).toBe(bar.getAttribute("aria-label"));
  }
});
