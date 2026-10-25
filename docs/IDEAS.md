# Ideas not built (yet)

Bigger "nice to have" ideas, one-line pitch each. Not commitments.

- **Generated API types:** export the engine's OpenAPI schema and generate TypeScript types so web and engine cannot drift.
- **Pre-commit hook:** run the fast half of the gate (lint, format, types) before each commit.
- **Import-boundary linter:** use `import-linter` contracts to enforce "checker never imports scheduler" in config as well as in a test.
