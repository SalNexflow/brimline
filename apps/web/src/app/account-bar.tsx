import Link from "next/link";

import { currentUser } from "@/lib/engine";

import { signOut } from "./actions";

export async function AccountBar() {
  const me = await currentUser();
  if (!me) {
    return <Link href="/login">Sign in</Link>;
  }
  return (
    <div className="account">
      <span data-testid="signed-in-as">
        {me.display_name} <span className="badge">{me.role}</span>
        {me.customer_name ? <span className="muted"> · {me.customer_name}</span> : null}
      </span>
      <form action={signOut}>
        <button type="submit" className="link-button">
          Sign out
        </button>
      </form>
    </div>
  );
}
