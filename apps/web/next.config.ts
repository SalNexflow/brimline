import path from "node:path";

import type { NextConfig } from "next";

// The pnpm workspace root (two levels up). Set explicitly so Next never has to guess it from
// lockfiles in parent folders, for example when the gate self-test runs in a copy inside the repo.
const workspaceRoot = path.resolve(__dirname, "..", "..");

const nextConfig: NextConfig = {
  cacheComponents: true,
  partialPrefetching: true,
  turbopack: { root: workspaceRoot },
  outputFileTracingRoot: workspaceRoot,
  // Model files go through a server action to the engine, which allows 25 MiB
  // (config/files.toml); the default action body limit is 1 MB.
  experimental: { serverActions: { bodySizeLimit: "26mb" } },
};

export default nextConfig;
