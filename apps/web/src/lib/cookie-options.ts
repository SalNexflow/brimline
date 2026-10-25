// Kept free of server-only imports so the rules can be unit-tested directly.

export const SESSION_COOKIE = "brimline_session";

export type SessionCookieOptions = {
  httpOnly: true;
  sameSite: "lax";
  secure: boolean;
  path: "/";
  expires: Date;
};

/**
 * httpOnly: page scripts cannot read the token, so an injected script cannot steal it.
 * sameSite "lax": the cookie is not sent on cross-site form posts, which blocks login CSRF.
 * secure in production: only sent over HTTPS (browsers treat localhost as secure too).
 * expires: matches the engine's token expiry, so the browser drops it when it stops working.
 */
export function sessionCookieOptions(expiresAt: Date, production: boolean): SessionCookieOptions {
  return { httpOnly: true, sameSite: "lax", secure: production, path: "/", expires: expiresAt };
}
