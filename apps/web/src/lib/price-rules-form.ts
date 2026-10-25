import { z } from "zod";

// The "new price version" form. Rates are whole cents; the engine validates again and decides.

const cents = (label: string) =>
  z
    .string()
    .trim()
    .transform((value, ctx) => {
      const n = Number(value);
      if (value === "" || !Number.isInteger(n) || n < 0 || n > 10_000_000) {
        ctx.addIssue({ code: "custom", message: `${label} must be a whole number of cents from 0 to 10,000,000` });
        return z.NEVER;
      }
      return n;
    });

export type PriceRulesBody = {
  effective_from: string;
  setup_cents: number;
  rush_multiplier_percent: number;
  material_cents_per_gram: Record<string, number>;
  machine_cents_per_minute: { fdm: number; resin: number; cnc: number };
  post_process_cents_per_part: { sanding: number; painting: number; assembly: number };
  note: string;
};

export type PriceRulesResult = { ok: true; value: PriceRulesBody } | { ok: false; errors: string[] };

/** Material rates arrive as material_<CODE>; `material_codes` lists which codes to read. */
export function parsePriceRules(form: FormData): PriceRulesResult {
  const text = (name: string) => String(form.get(name) ?? "");
  const codes = form.getAll("material_codes").map(String);
  const schema = z.object({
    effective_from: z.iso.date("Enter the date the new prices start"),
    setup_cents: cents("Setup"),
    rush_multiplier_percent: z.coerce
      .number({ error: "Rush multiplier must be a number" })
      .int("Rush multiplier must be a whole percentage")
      .min(100, "Rush multiplier must be at least 100 %")
      .max(500, "Rush multiplier can be at most 500 %"),
    material_cents_per_gram: z.object(Object.fromEntries(codes.map((code) => [code, cents(`${code} rate`)]))),
    machine_cents_per_minute: z.object({ fdm: cents("FDM rate"), resin: cents("Resin rate"), cnc: cents("CNC rate") }),
    post_process_cents_per_part: z.object({
      sanding: cents("Sanding"),
      painting: cents("Painting"),
      assembly: cents("Assembly"),
    }),
    note: z.string().trim().max(500, "The note can be at most 500 characters"),
  });
  const result = schema.safeParse({
    effective_from: text("effective_from"),
    setup_cents: text("setup_cents"),
    rush_multiplier_percent: text("rush_multiplier_percent"),
    material_cents_per_gram: Object.fromEntries(codes.map((code) => [code, text(`material_${code}`)])),
    machine_cents_per_minute: { fdm: text("machine_fdm"), resin: text("machine_resin"), cnc: text("machine_cnc") },
    post_process_cents_per_part: {
      sanding: text("post_sanding"),
      painting: text("post_painting"),
      assembly: text("post_assembly"),
    },
    note: text("note"),
  });
  if (result.success) return { ok: true, value: result.data as PriceRulesBody };
  return { ok: false, errors: [...new Set(result.error.issues.map((issue) => issue.message))] };
}
