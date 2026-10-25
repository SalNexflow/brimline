import { connection } from "next/server";
import { Suspense } from "react";

import { engineClient } from "@/lib/engine";

import { signIn } from "../actions";

export default function LoginPage({ searchParams }: PageProps<"/login">) {
  return (
    <main className="page">
      <h1>Sign in</h1>
      <p className="muted">
        Demo accounts only: pick a person to see the shop through their role. No passwords.
      </p>
      <Suspense fallback={<p>Loading demo accounts…</p>}>
        <DemoUsers searchParams={searchParams} />
      </Suspense>
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
      {failed ? <p role="alert">Sign-in failed. Try again.</p> : null}
      <ul className="user-list">
        {users.map((user) => (
          <li key={user.code}>
            <form action={signIn}>
              <input type="hidden" name="user_code" value={user.code} />
              <button type="submit" aria-label={`Sign in as ${user.display_name}, ${user.role}`}>
                <strong>{user.display_name}</strong>
                <span className="badge">{user.role}</span>
                {user.customer_name ? <span className="muted">{user.customer_name}</span> : null}
              </button>
            </form>
          </li>
        ))}
      </ul>
    </>
  );
}
