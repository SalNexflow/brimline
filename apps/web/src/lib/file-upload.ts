import { z } from "zod";

// What the model-file upload form may send. The engine checks everything again (and reads the
// file itself); this only gives quick, plain messages before a large upload is sent.

export const MAX_UPLOAD_BYTES = 25 * 1024 * 1024; // config/files.toml [limits] max_upload_bytes
export const UNITS = ["millimeter", "inch", "centimeter", "meter", "micron", "foot"] as const;

const uploadSchema = z
  .object({
    quote: z
      .string()
      .transform((v) => (v === "" ? null : v))
      .pipe(z.string().regex(/^Q-[0-9]{4,10}$/, "Unknown quote number").nullable()),
    order: z
      .string()
      .transform((v) => (v === "" ? null : v))
      .pipe(z.string().regex(/^BL-[0-9]{4,10}$/, "Unknown order number").nullable()),
    line: z.coerce.number().int("Line must be a whole number").min(1, "Line must be 1 or more").max(50),
    unit: z.enum(UNITS, "Choose a unit"),
    filename: z
      .string()
      .min(1, "Choose a file")
      .max(200, "The file name is too long")
      .regex(/\.(stl|3mf)$/i, "Only STL and 3MF files can be checked"),
    size: z.number().min(1, "The file is empty").max(MAX_UPLOAD_BYTES, "The file is larger than 25 MiB"),
  })
  .refine((v) => (v.quote === null) !== (v.order === null), "Give either a quote or an order");

export type UploadValues = z.infer<typeof uploadSchema>;
export type UploadResult = { ok: true; value: UploadValues } | { ok: false; errors: string[] };

export function parseUpload(form: FormData): UploadResult {
  const file = form.get("file");
  const isFile = typeof file === "object" && file !== null && "size" in file;
  const result = uploadSchema.safeParse({
    quote: String(form.get("quote") ?? ""),
    order: String(form.get("order") ?? ""),
    line: String(form.get("line") ?? ""),
    unit: String(form.get("unit") ?? "millimeter"),
    filename: isFile ? (file as File).name : "",
    size: isFile ? (file as File).size : 0,
  });
  if (result.success) return { ok: true, value: result.data };
  return { ok: false, errors: [...new Set(result.error.issues.map((issue) => issue.message))] };
}

/** "BL-0008-2" -> order BL-0008, line 2 (the board's job keys). */
export function splitJobKey(key: string): { order: string; line: number } | null {
  const match = /^(BL-[0-9]{4,10})-([0-9]{1,2})$/.exec(key);
  if (!match || match[1] === undefined) return null;
  return { order: match[1], line: Number(match[2]) };
}
