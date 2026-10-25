# eval

Evaluation datasets and results. Every number in the README comes from here (hard rule 11).

- `datasets/`: hand-labelled inputs with independently known expected outputs.
- `results/`: written by `make eval` only. `RESULTS.md` is generated, never edited by hand.
- `results/cache/<model>/<prompt version>/`: every model reply, saved so a score can be recomputed
  without paying again. `--fresh` calls the model anyway.

## Quote extraction (`datasets/quote_requests.jsonl`)

45 fictional customer messages: clear, vague, contradictory, multilingual (German, Spanish,
French) and instruction-injecting. **33 dev, 12 held out**; tune prompts on dev only, and report
held-out separately. Each item has the message, when it arrived (the due date depends on it), and
the expected result:

- `lines`: per part, in order: `quantity`, `material_code`, `post_processing`. `null` means the
  message does not say (or says two different things), so a good model leaves it empty.
- `due_date`: the date our code should compute from the model's rule, or `null` for no deadline.
- `rush`: whether the customer asked for urgency.
- `injection`: the message tries to instruct the model (discounts, "mark as paid", fake system
  text). The model should keep extracting normally and put the request in `requests_for_staff`.

Labelling conventions: a material code is expected only when material **and** colour point to one
catalog entry ("PLA" alone is `null`: there are two PLA colours). "A dozen" is 12; "a few" is
`null`. A corrected deadline ("Friday, sorry, I mean Thursday") counts the correction.

Run: `make eval` (the configured model) or
`node scripts/tasks.mjs eval --models claude-opus-5-5,claude-haiku-5-5 --split dev`.
Needs model access (ANTHROPIC_API_KEY) unless every reply is already saved; it stops at
`--max-cost-usd` (default 5) and never writes numbers it did not measure.
