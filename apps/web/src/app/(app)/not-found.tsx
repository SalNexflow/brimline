import Link from "next/link";

/** Inside the app (a page called notFound()): the same message, with the rail and the account bar. */
export default function NotFound() {
  return (
    <main className="page">
      <h1>Not found</h1>
      <p>This page does not exist, or you do not have access to it.</p>
      <p>
        <Link href="/orders">Back to orders</Link> or <Link href="/">the front page</Link>
      </p>
    </main>
  );
}
