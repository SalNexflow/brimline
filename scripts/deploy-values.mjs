#!/usr/bin/env node
// Prints fresh secret values for the hosted demo (docs/DEPLOY.md), and where each one goes.
// Run it once on your own machine; the values are printed only to your terminal, never saved.
//   node scripts/deploy-values.mjs "<Neon owner connection string>"
import { randomBytes } from "node:crypto";

const owner = process.argv[2];
if (!owner || !owner.startsWith("postgres")) {
  console.error('Usage: node scripts/deploy-values.mjs "postgresql://neondb_owner:...@...neon.tech/neondb?sslmode=require"');
  process.exit(2);
}
const webKey = randomBytes(32).toString("base64url");
const appPassword = randomBytes(24).toString("base64url");
const app = new URL(owner);
app.username = "brimline_app";
app.password = appPassword;

console.log(`
Render (engine) and GitHub secrets — the database:
  DATABASE_OWNER_URL / DEMO_DATABASE_OWNER_URL = ${owner}
  DATABASE_URL       / DEMO_DATABASE_URL       = ${app.toString()}

Render (engine) and Vercel (web) — the same value in both:
  ENGINE_WEB_KEY = ${webKey}

Render only:
  DEEPSEEK_API_KEY = (your key; leave it out to run the demo with replayed replies only)

Vercel only:
  ENGINE_URL      = https://<your-render-service>.onrender.com
  DEMO_WAKE_CHECK = 1

GitHub secrets, from this repository's folder (gh is already signed in on this machine):
  gh secret set DEMO_DATABASE_OWNER_URL --body "${owner}"
  gh secret set DEMO_DATABASE_URL --body "${app.toString()}"
`);
