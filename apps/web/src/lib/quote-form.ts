import { z } from "zod";

// What the quote review form may send. The engine validates again and decides; this only
// gives staff quick messages. Empty optional fields mean "not known yet" (null), never zero.

const POST_PROCESSING = ["sanding", "painting", "assembly"] as const;

const optionalCount = (label: string, max: number) =>
  z
    .string()
    .trim()
    .transform((value, ctx) => {
      if (value === "") return null;
      const n = Number(value);
      if (!Number.isInteger(n) || n < 1 || n > max) {
        ctx.addIssue({ code: "custom", message: `${label} must be a whole number from 1 to ${max.toLocaleString("en")}` });
        return z.NEVER;
      }
      return n;
    });

const lineSchema = z.object({
  part_name: z.string().trim().min(1, "Every line needs a part name").max(200),
  quantity: optionalCount("Quantity", 10_000),
  material_code: z
    .string()
    .transform((v) => (v === "" ? null : v)),
  grams_per_part: optionalCount("Grams per part", 100_000),
  minutes_per_part: optionalCount("Minutes per part", 100_000),
  part_mm: z
    .tuple([optionalCount("Part size", 5000), optionalCount("Part size", 5000), optionalCount("Part size", 5000)])
    .transform((size, ctx) => {
      if (size.every((v) => v === null)) return null;
      if (size.some((v) => v === null)) {
        ctx.addIssue({ code: "custom", message: "Give all three part sizes, or none" });
        return z.NEVER;
      }
      return size as [number, number, number];
    }),
  post_processing: z.array(z.enum(POST_PROCESSING)),
});

export const quoteEditSchema = z.object({
  due_date: z
    .string()
    .transform((v) => (v === "" ? null : v))
    .pipe(z.iso.date("Enter a valid due date").nullable()),
  rush: z.boolean(),
  notes: z.string().trim().max(2000, "Notes can be at most 2,000 characters"),
  lines: z.array(lineSchema).min(1, "Keep at least one line").max(50),
});

export type QuoteEditValues = z.infer<typeof quoteEditSchema>;
export type QuoteEditResult = { ok: true; value: QuoteEditValues } | { ok: false; errors: string[] };

/** Lines are named line_<id>_<field>; `line_ids` lists the rows in their on-screen order. */
export function parseQuoteEdit(form: FormData): QuoteEditResult {
  const text = (name: string) => String(form.get(name) ?? "");
  const ids = form.getAll("line_ids").map(String);
  const result = quoteEditSchema.safeParse({
    due_date: text("due_date"),
    rush: form.get("rush") === "on",
    notes: text("notes"),
    lines: ids.map((id) => ({
      part_name: text(`line_${id}_part_name`),
      quantity: text(`line_${id}_quantity`),
      material_code: text(`line_${id}_material_code`),
      grams_per_part: text(`line_${id}_grams_per_part`),
      minutes_per_part: text(`line_${id}_minutes_per_part`),
      part_mm: [text(`line_${id}_part_x`), text(`line_${id}_part_y`), text(`line_${id}_part_z`)],
      post_processing: form.getAll(`line_${id}_post_processing`).map(String),
    })),
  });
  if (result.success) return { ok: true, value: result.data };
  return { ok: false, errors: [...new Set(result.error.issues.map((issue) => issue.message))] };
}
