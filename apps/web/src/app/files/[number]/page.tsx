import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { Suspense } from "react";

import { signedInEngine, type FileReport } from "@/lib/engine";

import { AcceptWarningForm, AdviceForm } from "../forms";

export const metadata: Metadata = { title: "File check · Brimline" };

const CHECK_LABELS: Record<string, string> = {
  parse: "File reads",
  units: "Size and unit",
  watertight: "Closed surface",
  fits: "Fits a machine",
  walls: "Wall thickness",
  overhangs: "Overhangs",
  loose_parts: "Loose parts",
};
const STATUS_LABELS: Record<string, string> = { pass: "Pass", warn: "Warning", fail: "Fail", skip: "Not checked" };

export default function FilePage({ params }: PageProps<"/files/[number]">) {
  return (
    <main className="page">
      <Suspense fallback={<p>Loading the file check…</p>}>
        <FileCheck params={params} />
      </Suspense>
    </main>
  );
}

async function FileCheck({ params }: Pick<PageProps<"/files/[number]">, "params">) {
  const { number } = await params;
  const { client } = await signedInEngine();
  const { data: file } = await client.GET("/files/{file_number}", { params: { path: { file_number: number } } });
  if (!file) notFound();
  const back = file.quote_number ? `/quotes/${file.quote_number}` : `/orders/${file.order_number}`;
  const owner = file.quote_number ? `quote ${file.quote_number}` : `order ${file.order_number}`;
  const accepted = new Set(file.overrides.map((o) => o.check));
  const m = file.report.measurements;
  return (
    <>
      <p>
        <Link href={back}>← Back to {owner}</Link>
      </p>
      <h1>
        File {file.file_number}{" "}
        <span className={`check check-${file.overall}`} data-testid="file-overall">
          {STATUS_LABELS[file.overall]}
        </span>
      </h1>
      <p>
        {file.filename} for {owner}, line {file.line}
        {file.material_code ? ` (${file.material_code})` : ""}. Uploaded by {file.uploaded_by}. Every result below is
        measured by code against the shop settings in <code>config/files.toml</code>.
      </p>

      {m ? (
        // A plain picture drawn by code: three views of the part.
        // eslint-disable-next-line @next/next/no-img-element
        <img
          className="file-preview"
          src={`/files/${file.file_number}/preview`}
          alt={`Top, front and side views of ${file.filename}`}
          width={680}
          height={220}
        />
      ) : null}

      <h2>Checks</h2>
      <table>
        <thead>
          <tr>
            <th scope="col">Check</th>
            <th scope="col">Result</th>
            <th scope="col">Why</th>
          </tr>
        </thead>
        <tbody>
          {file.report.checks.map((c) => (
            <tr key={c.name}>
              <td>{CHECK_LABELS[c.name] ?? c.name}</td>
              <td>
                <span className={`check check-${c.status}`}>{STATUS_LABELS[c.status]}</span>
                {accepted.has(c.name) ? <span className="muted"> (accepted)</span> : null}
              </td>
              <td>
                {c.reason}
                {c.status === "warn" && file.can_override && !accepted.has(c.name) ? (
                  <AcceptWarningForm fileNumber={file.file_number} check={c.name} formKey={crypto.randomUUID()} />
                ) : null}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {file.overrides.length > 0 ? (
        <>
          <h3>Accepted warnings</h3>
          <ul>
            {file.overrides.map((o) => (
              <li key={o.check}>
                {CHECK_LABELS[o.check] ?? o.check}: “{o.reason}” ({o.by})
              </li>
            ))}
          </ul>
        </>
      ) : null}

      <Planning file={file} />

      <section aria-labelledby="advice-heading" className="advice">
        <h2 id="advice-heading">Advice (AI, not a check)</h2>
        <p className="muted">
          Optional comments from a vision model on the picture above. They never change a check, the verdict or any
          number.
        </p>
        {file.advice.length > 0 ? (
          file.advice.map((a, i) => (
            <ul key={i} aria-label={`Advice from ${a.model ?? "a model"}`}>
              {a.advice.map((note) => (
                <li key={note}>{note}</li>
              ))}
            </ul>
          ))
        ) : (
          <p>No advice{file.can_ask_advice ? " yet" : " (switched off in the shop settings)"}.</p>
        )}
        {file.can_ask_advice ? <AdviceForm fileNumber={file.file_number} formKey={crypto.randomUUID()} /> : null}
      </section>
    </>
  );
}

function Planning({ file }: { file: FileReport }) {
  const p = file.planning;
  const m = file.report.measurements;
  return (
    <section aria-labelledby="planning-heading">
      <h2 id="planning-heading">What the file gives the plan</h2>
      <dl className="facts">
        <dt>Part size</dt>
        <dd data-testid="file-part-size">{p.part_mm ? `${p.part_mm.join(" x ")} mm (rounded up)` : "not used"}</dd>
        <dt>Grams per part</dt>
        <dd>{p.grams_per_part ?? "not estimated"}</dd>
        <dt>Print minutes per part</dt>
        <dd>{p.minutes_per_part ?? "not estimated"}</dd>
        {m ? (
          <>
            <dt>Measured</dt>
            <dd>
              {m.size_mm.map((s) => s.toFixed(2)).join(" x ")} mm, {m.triangles.toLocaleString("en")} triangles
              {m.volume_mm3 !== null ? `, ${(m.volume_mm3 / 1000).toFixed(2)} cm³` : ""}
            </dd>
          </>
        ) : null}
      </dl>
      {p.notes.length > 0 ? (
        <ul className="muted">
          {p.notes.map((n) => (
            <li key={n}>{n}</li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}
