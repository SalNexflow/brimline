# scripts

- `tasks.mjs`: the single task runner. `make <task>` and `pnpm <task>` both call it, so commands behave the same in PowerShell, Git Bash, and CI.
- `gate_selftest.mjs`: proves the gate is not a rubber stamp by planting deliberate errors in a throwaway copy of the repo.
