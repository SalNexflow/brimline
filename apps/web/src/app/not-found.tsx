import Link from "next/link";

export default function NotFound() {
  return (
    <main className="page">
      <h1>Not found</h1>
      <p>This page does not exist, or you do not have access to it.</p>
      <p>
        <Link href="/orders">Back to orders</Link>
      </p>
    </main>
  );
}
