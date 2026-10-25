# Decisions

Every decision, deviation from the brief, and addition. Newest at the bottom of each milestone. Keep entries short:
**what**, **why**, **alternative considered**.

## M0. Scaffold and quality gate (2026-10-25)

| # | Decision | Why | Alternative considered |
|---|---|---|---|
| D1 | Moved `BRIEF.md` and `MILESTONES.md` into `docs/`. | CLAUDE.md refers to `docs/BRIEF.md`; paths should match the instructions. | Leave them in the root and edit CLAUDE.md. |
| D2 | Added `config/` (dated config) to the suggested layout. | Hard rule 8 ("config, not memory") needs one obvious home for model names, prices, thresholds, weights. | Scatter config per service. |
| D3 | All task logic lives in one Node script, `scripts/tasks.mjs`. `make <x>` and `pnpm run <x>` are thin aliases of it. | Tested on this machine: from PowerShell, GNU make ran recipes with `cmd.exe` (and `bash` on PATH is WSL, not Git Bash); from Git Bash it used bash. Node is always installed and behaves the same everywhere. Verified `make gate` and `pnpm run gate` from both shells. | Shell recipes in the Makefile (flaky across shells); `just` (another tool to install). |
| D4 | Python tooling is **uv** with `uv.lock`, Python pinned to 3.12. | One command creates the venv with the right Python; lockfile makes installs reproducible. 3.12 is the safest version for OR-Tools (M3) and mypy. | pip + venv + requirements.txt; Python 3.14 (newer, wheel support less certain). |
| D5 | pnpm installed with `npm i -g pnpm`, not corepack. | `corepack enable` needs admin rights on Windows (EPERM writing to Program Files). | Run corepack as admin. |
| D6 | TypeScript pinned to 6.0.3, not 7.0. ESLint kept at 9, not 10. | `typescript-eslint` 8.72 (used by `eslint-config-next`) supports TypeScript `<6.1.0`. `create-next-app` 16.4.3 itself picks ESLint 9, and its React plugins are not confirmed on 10. | TypeScript 7 with no type-aware linting; ESLint 10. |
| D7 | PostgreSQL 18.6 (alpine) on host port 5433. | Current stable. 5433 avoids clashing with a locally installed Postgres. Volume mounts at `/var/lib/postgresql`, the Postgres 18 image layout. | Postgres 17. |
| D8 | Vitest for web unit tests, Playwright (Chromium only) for browser tests. | Vitest needs little config with TypeScript. Chromium only keeps setup and CI small. | Jest; all three Playwright browsers. |
| D9 | The gate does not touch the database in M0. | Nothing to test yet. `setup` starts Postgres and waits for its health check. DB tests join the gate in M1. | A ping test in M0 that proves little. |
| D10 | Added `gate-selftest`: refuses a dirty git tree, exports the last commit with `git archive` into `.selftest/` (git-ignored), requires a green baseline, then plants 8 errors one at a time (one per gate step except the build) and requires the gate to fail **at the step meant to catch it**. Deletes the copy afterwards. | Turns "the gate fails on errors" into a command result, not a claim (hard rule 11). The copy means the real tree is never modified. The baseline stops a broken copy from making every mutation look "caught". | A manual demonstration; mutating the real tree and restoring with git (risky if interrupted). |
| D11 | Engine tests use `httpx2`, and pytest treats warnings as errors. | Starlette 1.10 deprecated plain `httpx` for its TestClient. Failing on warnings surfaces the next deprecation instead of hiding it. | Keep `httpx` and ignore the warning. |
| D12 | System fonts, no `next/font/google`. Template logos and the default favicon removed; replaced with an original SVG mark. | Fetching fonts at build time makes the gate depend on the network. Default assets are a real company's branding. | Self-hosted font files (decide with the visual direction in M5). |
| D13 | The gate runs `next build`, and Playwright tests that production build on port 3100. | Build errors fail the gate. A separate port means a running `pnpm dev` can never be tested by mistake. | Test against `next dev` (faster, but skips the build). |
| D14 | `turbopack.root` and `outputFileTracingRoot` set to the repo root in `next.config.ts`. | Next guesses the workspace root from lockfiles in parent folders; the self-test copy sits inside the repo and could be mistaken for it. | Put the copy in the OS temp folder. |
| D15 | Compose uses a fixed project `name: brimline`, not a fixed `container_name`. | Every checkout shares one DB container instead of failing on a name clash (see DEFECT_LOG #1). | Per-checkout databases (more ports to manage). |
| D16 | `typecheck` runs `next typegen` before `tsc`. Next telemetry is disabled in the task runner. | Route types such as `LayoutProps` exist only after typegen, so a fresh clone failed `tsc` without it. A quality gate should not send telemetry. | Commit generated types. |
