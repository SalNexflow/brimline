import { connection } from "next/server";
import { Suspense } from "react";

import { engineClient } from "@/lib/engine";

import { signIn } from "../../actions";
import { SignInButton } from "./sign-in-button";

export default function LoginPage({ searchParams }: PageProps<"/login">) {
  return (
    <main className="page">
      <section className="login-card" aria-labelledby="sign-in-heading">
        <span className="brand-mark login-mark" aria-hidden="true" />
        <h1 id="sign-in-heading">Sign in</h1>
        <p className="muted">Demo accounts only: pick a person to see the shop through their role. No passwords.</p>
        <Suspense fallback={<p>Loading demo accounts…</p>}>
          <DemoUsers searchParams={searchParams} />
        </Suspense>
      </section>
    </main>
  );
}

async function DemoUsers({ searchParams }: Pick<PageProps<"/login">, "searchParams">) {
  // Request-time data: mark it dynamic before any I/O, so the build never calls the engine.
  await connection();
  const failed = (await searchParams).error !== undefined;
  const { data: users, response } = await engineClient().GET("/auth/demo-users");

  if (response.status === 404) {
    return <p role="status">Demo login is switched off on this server.</p>;
  }
  if (!users) {
    return <p role="alert">The engine is not reachable. Is it running?</p>;
  }
  return (
    <>
      {failed ? (
        <p role="alert" className="error-box">
          Sign-in failed. Try again.
        </p>
      ) : null}
      <ul className="user-list">
        {users.map((user) => (
          <li key={user.code}>
            <form action={signIn}>
              <input type="hidden" name="user_code" value={user.code} />
              <SignInButton>
                <span className="avatar" aria-hidden="true" />
                {/* The button's name is its visible words, with "Sign in as" and a comma for
                    screen readers: "Sign in as Sam Ortega, staff" (WCAG 2.5.3, label in name). */}
                <span>
                  <span className="visually-hidden">Sign in as</span> <strong>{user.display_name}</strong>
                  <span className="silent">,</span> <span className="badge">{user.role}</span>
                </span>
                {user.customer_name ? <span className="muted">{user.customer_name}</span> : null}
              </SignInButton>
            </form>
          </li>
        ))}
      </ul>
    </>
  );
}
