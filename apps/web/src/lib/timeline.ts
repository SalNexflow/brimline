// Pure helpers for the production board's time axis. All instants are ISO strings or Dates in
// UTC; they are shown in the shop's time zone, which the engine sends with the board.

const MINUTE = 60_000;
const DAY = 24 * 60 * MINUTE;

/** The wall clock in `timeZone` at `instant`, read as if it were UTC (a "wall" timestamp). */
function wallAsUtc(instant: number, timeZone: string): number {
  const parts = new Intl.DateTimeFormat("en-GB", {
    timeZone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hourCycle: "h23",
  }).formatToParts(new Date(instant));
  const get = (type: string) => Number(parts.find((p) => p.type === type)?.value ?? 0);
  return Date.UTC(get("year"), get("month") - 1, get("day"), get("hour"), get("minute"), get("second"));
}

/** The instant of midnight in `timeZone` on the day `instant` falls on. Take the local date,
 * then find the instant whose wall clock reads that date at 00:00: the zone's offset is looked
 * up at a first guess and corrected once, so a day with a clock change still lands on 00:00. */
export function startOfShopDay(instant: Date, timeZone: string): Date {
  const wall = wallAsUtc(instant.getTime(), timeZone);
  const midnightWall = wall - (wall % DAY);
  let guess = midnightWall - (wallAsUtc(midnightWall, timeZone) - midnightWall);
  guess = midnightWall - (wallAsUtc(guess, timeZone) - guess);
  return new Date(guess);
}

export type Window = { from: Date; to: Date; days: Date[] };

/** The next local midnight after the midnight `day`. Steps a day and two hours, then snaps
 * back to midnight, so a 23- or 25-hour day around a clock change still lands on 00:00. */
function nextShopDay(day: Date, timeZone: string): Date {
  return startOfShopDay(new Date(day.getTime() + DAY + 2 * 60 * MINUTE), timeZone);
}

/** The span the board shows: whole shop days from the day of `start` until every `end` fits,
 * at least `minDays` days. `days` holds each day's midnight; `to` is the midnight after. */
export function boardWindow(start: Date, ends: Date[], timeZone: string, minDays = 3): Window {
  const from = startOfShopDay(start, timeZone);
  const last = ends.reduce((a, b) => (b > a ? b : a), start);
  const days = [from];
  let to = nextShopDay(from, timeZone);
  while (to < last || days.length < minDays) {
    days.push(to);
    to = nextShopDay(to, timeZone);
  }
  return { from, to, days };
}

/** Where `instant` sits in the window, as a percentage of its width (clamped to 0..100). */
export function percentAt(instant: Date, w: Pick<Window, "from" | "to">): number {
  const span = w.to.getTime() - w.from.getTime();
  const p = ((instant.getTime() - w.from.getTime()) / span) * 100;
  return Math.min(100, Math.max(0, p));
}

/** Greedy lanes for intervals that may overlap (manual work: several people at once). Returns
 * each interval's lane, in input order; intervals touching end-to-start share a lane. */
export function lanes(intervals: { start: Date; end: Date }[]): number[] {
  const order = intervals
    .map((iv, index) => ({ index, start: iv.start.getTime(), end: iv.end.getTime() }))
    .sort((a, b) => a.start - b.start);
  const laneEnds: number[] = [];
  const out = new Array<number>(intervals.length).fill(0);
  for (const iv of order) {
    let lane = laneEnds.findIndex((end) => end <= iv.start);
    if (lane === -1) lane = laneEnds.push(0) - 1;
    laneEnds[lane] = iv.end;
    out[iv.index] = lane;
  }
  return out;
}

/** A stable colour token per material: the same material is the same colour on every bar.
 * Colour is never the only signal; bars also carry the material's code as text. */
export function materialToken(code: string, allCodes: string[]): string {
  const sorted = [...new Set(allCodes)].sort();
  const index = Math.max(0, sorted.indexOf(code));
  return `var(--bar-${(index % 6) + 1})`;
}

export function formatShopTime(instant: Date | string, timeZone: string): string {
  return new Intl.DateTimeFormat("en-GB", {
    timeZone,
    weekday: "short",
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).format(new Date(instant));
}

export function formatShopDay(instant: Date, timeZone: string): string {
  return new Intl.DateTimeFormat("en-GB", { timeZone, weekday: "short", day: "numeric", month: "short" }).format(
    instant,
  );
}

export function formatDuration(minutes: number): string {
  const h = Math.floor(minutes / 60);
  const m = Math.round(minutes % 60);
  return h ? `${h} h ${m} min` : `${m} min`;
}

/** A UTC instant as the value of a datetime-local input showing shop time ("2026-11-03T17:00"). */
export function utcToShopLocal(instant: string | Date, timeZone: string): string {
  const wall = new Date(wallAsUtc(new Date(instant).getTime(), timeZone));
  return wall.toISOString().slice(0, 16);
}

/** A datetime-local value typed in shop time, as a UTC ISO string; null if it is not a time.
 * In the hour that happens twice when clocks go back, the first one is meant. */
export function shopLocalToUtc(local: string, timeZone: string): string | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})$/.exec(local);
  if (!m) return null;
  const wall = Date.UTC(+m[1]!, +m[2]! - 1, +m[3]!, +m[4]!, +m[5]!);
  let guess = wall - (wallAsUtc(wall, timeZone) - wall);
  guess = wall - (wallAsUtc(guess, timeZone) - guess);
  return new Date(guess).toISOString();
}
