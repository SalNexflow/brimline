/** Whether the engine is awake, for the waking-up screen (the engine's /health needs no key). */
export async function GET() {
  try {
    const r = await fetch(`${process.env.ENGINE_URL}/health`, { cache: "no-store", signal: AbortSignal.timeout(4000) });
    return new Response(r.ok ? "awake" : "asleep", { status: r.ok ? 200 : 503 });
  } catch {
    return new Response("asleep", { status: 503 });
  }
}
