# Deploying the public demo

Three free tiers, chosen in M11 (docs/DECISIONS.md D127), terms read on 2026-10-28:

| Part | Host | Free tier, as read | Why |
|---|---|---|---|
| Web (Next.js) | Vercel Hobby | Free, personal and non-commercial use; request bodies up to about 4.5 MB | Built for Next.js; no sleep |
| Engine (FastAPI, Docker) | Render free web service | 750 instance hours a month; sleeps after 15 idle minutes and takes about a minute to wake | Runs our Dockerfile as it is |
| Database (Postgres) | Neon Free | 1 GB per project, no card, suspends after 5 idle minutes | Does not expire (Render's free Postgres expires after 30 days) |

Everything that does not need your login is already in the repository: `render.yaml` (the
engine), `services/engine/Dockerfile`, `.github/workflows/demo-reset.yml` (nightly reset),
`config/demo.toml` (limits) and `scripts/deploy-values.mjs` (secrets). No payment method is needed
on any of the three.

## Your steps (each needs your login; sign in with GitHub everywhere)

1. **Neon:** at console.neon.tech, create a project named `brimline` (region Frankfurt). Copy
   its connection string (role `neondb_owner`, with `?sslmode=require`).
2. **Values:** in this folder run `node scripts/deploy-values.mjs "<that connection string>"`.
   It prints every secret and where it goes (nothing is saved).
3. **GitHub secrets:** run the two `gh secret set` lines it printed, then
   `gh workflow run demo-reset.yml` to create the demo data (watch it with `gh run watch`).
4. **Render:** at dashboard.render.com choose New → Blueprint, pick this repository, and paste
   the four values marked "sync: false" (`DATABASE_URL`, `DATABASE_OWNER_URL`,
   `ENGINE_WEB_KEY`, `DEEPSEEK_API_KEY`). Deploy, then copy the service's URL.
5. **Vercel:** at vercel.com choose Add New → Project, import this repository, set Root Directory
   to `apps/web`, add `ENGINE_URL` (the Render URL), `ENGINE_WEB_KEY` and `DEMO_WAKE_CHECK=1`,
   and deploy.

Then open the Vercel URL. The first visit after a quiet spell shows "The demo is waking up" for
about a minute while Render starts the engine.

## What runs where

- The engine migrates on every start (`db setup`) and is reset every night at 02:30 UTC by
  the GitHub workflow (`db reset --demo`: the seed moved to this week, a plan approved).
- `DEMO_MODE=true` applies `config/demo.toml`: a daily model budget and a per-visitor hourly
  limit (then recorded replies, or the by-hand path), a shorter solver run (labelled on the
  board), 4 MB uploads, and writes refused before the database nears 1 GB.
- `ENGINE_WEB_KEY` makes the engine answer only the web app; see docs/SECURITY.md for what is and
  is not hardened.
