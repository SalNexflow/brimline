import type { Metadata } from "next";
import Link from "next/link";

import results from "@/lib/results.generated.json";

import { signIn } from "./actions";
import { ThemeSwitch } from "./theme-switch";
import { TryButton } from "./try-button";

export const metadata: Metadata = {
  title: "Brimline: the system behind a 3D printing shop",
  description:
    "A portfolio demo: a fictional made-to-order 3D-print and CNC shop where AI reads the language and code decides prices, dates, permissions and plans.",
};

const REPO = "https://github.com/SalNexflow/brimline";
// The links to the source and the README show only while the repository is public (made public
// 2026-11-08); a private one would show visitors GitHub's 404 (D202).
const REPO_PUBLIC = true;

// The AI-versus-code boundary, shortened from the README's table (the same rules, fewer words).
const BOUNDARY: [string, string, string][] = [
  ["A customer's request", "Reads the message into a draft: parts, quantities, material, the date as written", "Works out the date, prices every line, lists what is missing; a person approves"],
  ["A 3D model file", "Nothing (optional advice, off by default)", "Measures the file: closed surface, size, fit per printer, walls, overhangs"],
  ["The day's plan", "Nothing", "A constraint solver plans; an independent checker re-checks every plan"],
  ["Starting machines", "Proposes which prints to start, then issues exactly the approved calls", "A person presses Proceed; a guard checks each call against the plan and the machine"],
  ["Something breaks", "Reads “printer 3 jammed until 5pm” into typed events", "Resolves the times, re-plans moving as little as it can; a planner approves"],
  ["Search", "Turns a question into a typed filter, never SQL", "Checks the filter, adds permissions, builds the query"],
];

// The three ways in, with the existing demo login (no passwords).
const PEOPLE = [
  { code: "U-HARBOR", role: "customer", name: "Mia Chen", what: "Ask for a quote, follow your orders" },
  { code: "U-PLANNER", role: "planner", name: "Priya Nandakumar", what: "Plan the day, handle a breakdown, dispatch" },
  { code: "U-OPERATOR", role: "operator", name: "Jonas Weber", what: "Work the queue, start and finish jobs" },
];

/** The front page, before sign-in (D202): static, built once, so it opens at once even while the free
    hosted engine sleeps. Someone already signed in goes straight into the app (proxy.ts). The app and
    every demo protection stay behind sign-in. */
export default function HomePage() {
  return (
    <div className="landing">
      <header className="landing-bar">
        <Link href="/" className="landing-brand" aria-label="Brimline home">
          <span className="brand-mark" aria-hidden="true" />
          <span>Brimline</span>
        </Link>
        <ThemeSwitch />
      </header>

      <main className="landing-main">
        <section className="landing-hero" aria-labelledby="landing-title">
          <p className="landing-eyebrow">The system behind a 3D printing shop</p>
          <h1 id="landing-title" className="landing-title">
            From a customer&apos;s message to a running print, with the AI kept in its place.
          </h1>
          <p className="landing-lede">
            Brimline takes a request and a 3D model file through a quote, an order, a plan across the machines and the
            day something breaks: AI reads the language, code decides prices, dates, permissions and plans.
          </p>
          <p role="note" className="notice landing-fiction">
            <strong>A demo, not a business.</strong> The shop, its customers and all data are fictional, and the machines
            are simulated. Nothing is for sale and nothing is printed.
          </p>
        </section>

        <section className="landing-try" aria-labelledby="try-heading">
          <h2 id="try-heading">Try it</h2>
          <p className="muted">Pick a person to see the shop through their role. Demo accounts, no passwords, reset every night.</p>
          <ul className="try-list">
            {PEOPLE.map((p) => (
              <li key={p.code}>
                <form action={signIn}>
                  <input type="hidden" name="user_code" value={p.code} />
                  <TryButton role={p.role} name={p.name} />
                  <p className="muted try-what">{p.what}</p>
                </form>
              </li>
            ))}
          </ul>
        </section>

        <section className="landing-video" aria-labelledby="video-heading">
          <h2 id="video-heading">The whole story in one walkthrough</h2>
          {/* No autoplay, controls always shown, nothing loads until asked (preload="none"). */}
          <video
            controls
            preload="none"
            poster="/media/brimline-demo-poster.jpg"
            width={1280}
            height={720}
            aria-labelledby="video-heading"
            aria-describedby="video-about"
          >
            <source src="/media/brimline-demo.mp4" type="video/mp4" />
            Your browser cannot play this video. <a href="/media/brimline-demo.mp4">Download it</a> instead.
          </video>
          <p className="muted" id="video-about">
            A 4-minute captioned walkthrough with the shop&apos;s fake data and replayed AI replies. It has no sound.
          </p>
        </section>

        <section className="landing-boundary" aria-labelledby="boundary-heading">
          <h2 id="boundary-heading">What the AI does, and what code decides</h2>
          <p className="muted">The AI reads language and explains. Anything with a price, a date, a permission or a plan is code.</p>
          {/* A diagram, one row per step: what the AI does on the left, what code decides on the right. */}
          <ol className="boundary">
            {BOUNDARY.map(([step, ai, code]) => (
              <li key={step} className="boundary-row">
                <h3 className="boundary-step">{step}</h3>
                <div className={`boundary-side side-ai${ai === "Nothing" ? " side-none" : ""}`}>
                  <span className="lane lane-ai">AI</span>
                  <p>{ai === "Nothing" ? "Nothing: no AI in this step" : ai}</p>
                </div>
                <span className="boundary-arrow" aria-hidden="true">
                  →
                </span>
                <div className="boundary-side side-code">
                  <span className="lane lane-code">Code</span>
                  <p>{code}</p>
                </div>
              </li>
            ))}
          </ol>
        </section>

        <section className="landing-results" aria-labelledby="results-heading">
          <h2 id="results-heading">Measured, not claimed</h2>
          <ul className="result-strip">
            {results.items.map((r) => (
              <li key={r.label} className="result">
                <span className="result-value">{r.value}</span>
                <span className="result-label">{r.label}</span>
                <span className="muted result-detail">{r.detail}</span>
                <code className="result-command">{r.command}</code>
              </li>
            ))}
          </ul>
          <ul className="caveats muted" aria-label="What these numbers do not show">
            {results.caveats.map((c) => (
              <li key={c}>{c}</li>
            ))}
          </ul>
        </section>

        {REPO_PUBLIC ? (
          <section className="landing-links" aria-labelledby="links-heading">
            <h2 id="links-heading">How it is built</h2>
            <p>
              <a href={REPO}>The source code</a> and <a href={`${REPO}#readme`}>the README</a>: architecture, every
              decision with its alternative, every bug and how it was caught.
            </p>
          </section>
        ) : null}
      </main>

      <footer className="landing-foot muted">
        Brimline is a portfolio project. The shop, its people and its data are fictional; the machines are simulated and
        untested on real hardware.
      </footer>
    </div>
  );
}
