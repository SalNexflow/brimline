# Thin aliases. All logic lives in scripts/tasks.mjs so commands behave the same in every shell
# (on Windows, GNU make runs recipes with cmd.exe or bash depending on where it is started).
# `pnpm run <task>` is the same thing for machines without make.

TASKS := setup dev gate test db-reset api-types eval bench replan-bench shortage-bench gate-selftest demo demo-smoke demo-stop screenshots demo-video readme
.PHONY: $(TASKS)

$(TASKS):
	node scripts/tasks.mjs $@
