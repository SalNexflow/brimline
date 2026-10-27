import { readSessionToken } from "@/lib/session";

/** The file's preview picture, fetched from the engine with the viewer's own session (the
 * engine checks they may see the file). */
export async function GET(_request: Request, { params }: RouteContext<"/files/[number]/preview">) {
  const { number } = await params;
  if (!/^F-[0-9]{4,10}$/.test(number)) return new Response("not found", { status: 404 });
  const token = await readSessionToken();
  if (!token) return new Response("sign in first", { status: 401 });
  const response = await fetch(`${process.env.ENGINE_URL}/files/${number}/preview.png`, {
    headers: { Authorization: `Bearer ${token}` },
    cache: "no-store",
  });
  if (!response.ok) return new Response("no preview", { status: response.status });
  return new Response(await response.arrayBuffer(), {
    headers: { "Content-Type": "image/png", "Cache-Control": "private, max-age=3600" },
  });
}
