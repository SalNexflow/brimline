import { expect, test } from "vitest";

import { sessionCookieOptions } from "./cookie-options";

const EXPIRES = new Date("2026-10-26T17:00:00Z");

test("the session cookie is httpOnly, SameSite=Lax, site-wide, and expires with the token", () => {
  expect(sessionCookieOptions(EXPIRES, false)).toEqual({
    httpOnly: true,
    sameSite: "lax",
    secure: false,
    path: "/",
    expires: EXPIRES,
  });
});

test("in production the cookie is only sent over HTTPS", () => {
  expect(sessionCookieOptions(EXPIRES, true).secure).toBe(true);
});
