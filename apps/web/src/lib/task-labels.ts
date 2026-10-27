// Plain names for the scheduler's four task kinds, used on the board and in the queues.
const KIND: Record<string, string> = {
  prep: "Prep",
  machine: "Machine run",
  post: "Post-processing",
  finish: "Check and pack",
};

export function kindLabel(kind: string): string {
  return KIND[kind] ?? kind;
}

const STATUS: Record<string, string> = {
  planned: "Planned",
  running: "Running",
  done: "Done",
  failed: "Failed",
  cancelled: "Cancelled",
};

export function statusLabel(status: string): string {
  return STATUS[status] ?? status;
}

/** The engine's reason for refusing, or a plain fallback (403 has its own wording). */
export function refusal(status: number, error: unknown, fallback: string): string {
  if (status === 403) return "You are not allowed to do this.";
  const detail = (error as { detail?: unknown } | undefined)?.detail;
  return typeof detail === "string" ? detail : fallback;
}
