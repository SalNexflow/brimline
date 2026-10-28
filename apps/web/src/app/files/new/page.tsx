import type { Metadata } from "next";
import Link from "next/link";
import { Suspense } from "react";

import { signedInEngine } from "@/lib/engine";
import { MAX_UPLOAD_BYTES } from "@/lib/file-upload";

import { UploadForm } from "../forms";

export const metadata: Metadata = { title: "Upload a model file · Brimline" };

export default function NewFilePage({ searchParams }: PageProps<"/files/new">) {
  return (
    <main className="page">
      <h1>Upload a model file</h1>
      <Suspense fallback={<p>Loading…</p>}>
        <NewFile searchParams={searchParams} />
      </Suspense>
    </main>
  );
}

async function NewFile({ searchParams }: Pick<PageProps<"/files/new">, "searchParams">) {
  const { client } = await signedInEngine(); // signed in; the engine checks who may upload where
  const { data: demo } = await client.GET("/demo-status");
  const query = await searchParams;
  const one = (v: string | string[] | undefined) => (Array.isArray(v) ? v[0] : v) ?? "";
  const quote = one(query.quote);
  const order = one(query.order);
  const line = Number(one(query.line) || "1");
  const back = quote ? `/quotes/${quote}` : order ? `/orders/${order}` : "/";
  return (
    <>
      <p>
        <Link href={back}>← Back</Link>
      </p>
      <p>
        For {quote ? `quote ${quote}` : `order ${order}`}, line {line}. The shop&apos;s code measures the file: whether
        it is closed, its size and whether it fits a machine, wall thickness, overhangs and loose parts. Where it
        can, it fills in the part size{quote ? ", and estimates grams and print minutes" : ""}. A value staff already
        entered is never replaced.
      </p>
      <UploadForm
        quote={quote || undefined}
        order={order || undefined}
        line={line}
        uploadKey={crypto.randomUUID()}
        maxBytes={demo?.max_upload_bytes ?? MAX_UPLOAD_BYTES}
      />
    </>
  );
}
