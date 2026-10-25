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
};

export default nextConfig;
