import { z } from "zod";

// What the create-order form may send. The engine validates again with its own schema and is
// the authority; this only gives people quick, friendly messages before a round trip.
const lineSchema = z.object({
  part_name: z.string().trim().min(1, "Every line needs a part name").max(200),
  quantity: z.coerce
    .number({ error: "Quantity must be a number" })
    .int("Quantity must be a whole number")
    .min(1, "Quantity must be at least 1")
    .max(10_000, "Quantity can be at most 10,000"),
  material_code: z.string().min(1, "Every line needs a material"),
});

export const orderFormSchema = z.object({
  customer_code: z.string().min(1, "Choose a customer"),
  due_date: z.iso.date("Enter a due date"),
  rush: z.boolean(),
  notes: z.string().trim().max(2000, "Notes can be at most 2,000 characters"),
  lines: z.array(lineSchema).min(1, "Add at least one line").max(50, "At most 50 lines"),
});

export type OrderFormValues = z.infer<typeof orderFormSchema>;

export type ParseResult = { ok: true; value: OrderFormValues } | { ok: false; errors: string[] };

/** Read the form's fields. Lines arrive as parallel lists; fully blank rows are ignored. */
export function parseOrderForm(form: FormData): ParseResult {
  const text = (name: string) => String(form.get(name) ?? "");
  const parts = form.getAll("line_part_name").map(String);
  const quantities = form.getAll("line_quantity").map(String);
  const materials = form.getAll("line_material_code").map(String);

  const lines = parts
    .map((part_name, i) => ({
      part_name,
      quantity: quantities[i] ?? "",
      material_code: materials[i] ?? "",
    }))
    .filter((line) => line.part_name.trim() !== "" || line.quantity.trim() !== "");

  const result = orderFormSchema.safeParse({
    customer_code: text("customer_code"),
    due_date: text("due_date"),
    rush: form.get("rush") === "on",
    notes: text("notes"),
    lines,
  });
  if (result.success) return { ok: true, value: result.data };
  return { ok: false, errors: [...new Set(result.error.issues.map((issue) => issue.message))] };
}
