// The "record a purchase order" form, read into the engine's request. The engine validates again;
// this only catches what a person can fix before sending, and turns shop time into UTC.

import { shopLocalToUtc } from "./timeline";

export type PurchaseOrderBody = { material_code: string; grams: number; supplier: string; expected_at: string };
type Parsed = { ok: true; value: PurchaseOrderBody } | { ok: false; errors: string[] };

export function parsePurchaseOrder(form: FormData, timeZone: string, now: Date = new Date()): Parsed {
  const get = (name: string) => String(form.get(name) ?? "").trim();
  const errors: string[] = [];
  const material = get("material_code");
  if (!material) errors.push("Choose a material.");
  const gramsText = get("grams");
  const grams = Number(gramsText);
  if (!/^[0-9]+$/.test(gramsText) || grams < 1 || grams > 1_000_000) {
    errors.push("Grams must be a whole number from 1 to 1,000,000.");
  }
  const supplier = get("supplier");
  if (!supplier || supplier.length > 100) errors.push("Name the supplier (up to 100 characters).");
  const local = get("expected_at");
  const expected = local ? shopLocalToUtc(local, timeZone) : null;
  if (!expected) errors.push("Give the expected delivery date and time.");
  else if (new Date(expected) < now) errors.push("The expected delivery time is in the past.");
  if (errors.length > 0 || !expected) return { ok: false, errors };
  return { ok: true, value: { material_code: material, grams, supplier, expected_at: expected } };
}
