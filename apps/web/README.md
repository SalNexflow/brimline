# apps/web

Next.js 16 (App Router) web app in TypeScript strict mode. It will hold the screens for every role: quotes, orders, the production board, approvals, and search.

| Script | What it does |
|---|---|
| `pnpm dev` | Dev server on port 3000 |
| `pnpm typecheck` | `next typegen` (route types such as `LayoutProps`) then `tsc --noEmit` |
| `pnpm lint` | ESLint with Next's rules; any warning fails |
| `pnpm test` | Vitest unit tests (`src/**/*.test.tsx`) in jsdom |
| `pnpm build` | Production build |
| `pnpm e2e` | Playwright browser tests (`e2e/`) against the production build on port 3100. Run `pnpm build` first. |

Notes:
- Styling uses CSS variables in `src/app/globals.css`, so the visual direction can change in M5 without touching components.
- System fonts only, so builds never need the network.
- `AGENTS.md` was written by `create-next-app`: it points coding agents to the docs bundled in `node_modules/next/dist/docs/`.
