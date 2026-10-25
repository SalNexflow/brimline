# Defect log

Every bug that was introduced and how it was caught. Honest entries only. A defect caught by the gate, a review,
or the independent checker is a success story, not an embarrassment.

| # | Date | Milestone | What was wrong | How it was introduced | How it was caught | Where caught (gate / test / review / checker / manual) | Fix and regression test |
|---|---|---|---|---|---|---|---|
| 1 | 2026-10-25 | M0 | `docker-compose.yml` fixed `container_name: brimline-db`, so a second checkout (a fresh clone) would fail to start its database on a name clash. | Copied a common compose habit without thinking about more than one checkout. | Noticed while preparing the fresh-clone acceptance test, before running it. | review | e10294d: fixed project `name: brimline` instead. Regression guard: the fresh-clone `make setup` run passed. No automated test, because compose behaviour is outside the gate. |
| 2 | 2026-10-25 | M0 | In CI, Playwright used only the `github` reporter, so the workflow's "upload report on failure" step would have uploaded nothing. | Wrote the reporter config before writing the workflow step that depends on it. | Read the config again while writing the workflow. | review | 65380c9: CI also writes the HTML report. Not yet verified on a real CI run (no remote yet). |
| 3 | 2026-10-25 | M0 | The first CI run failed before any step: `astral-sh/setup-uv@v10` could not be resolved. | Assumed every action publishes a floating major tag; I checked the latest release number but not that the `v10` tag exists. setup-uv publishes only full version tags. | First CI run 40184587351. | gate (CI) | Pinned setup-uv to the v10.3.2 commit SHA. The CI run itself is the regression check. |
