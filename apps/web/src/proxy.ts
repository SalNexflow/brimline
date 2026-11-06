import { NextResponse, type NextRequest } from "next/server";

import { SESSION_COOKIE } from "./lib/cookie-options";

/** The front page is for people who have not signed in: with a session cookie, go straight into the
    app. Only a shortcut: the engine still checks the session on every request, and an expired one
    lands on the sign-in page as before (D202). */
export function proxy(request: NextRequest) {
  if (request.cookies.has(SESSION_COOKIE)) return NextResponse.redirect(new URL("/orders", request.url));
  return NextResponse.next();
}

export const config = { matcher: "/" };
