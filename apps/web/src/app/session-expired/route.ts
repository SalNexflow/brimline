import { NextResponse, type NextRequest } from "next/server";

import { SESSION_COOKIE } from "@/lib/cookie-options";

/** A session the engine no longer accepts (expired, signed out elsewhere, or the demo's nightly
    reset): forget the cookie, then sign in again. Without this, the front page's shortcut into the
    app (proxy.ts) would keep sending a returning visitor round to the sign-in page instead of showing
    the front page (review of D202). Clears only the browser's own cookie; nothing else changes. */
export function GET(request: NextRequest) {
  const response = NextResponse.redirect(new URL("/login", request.url));
  response.cookies.delete(SESSION_COOKIE);
  return response;
}
