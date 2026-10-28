# Recorded model replies

`demo.jsonl` holds model replies recorded once with a live model (`AI_MODE=record`), one per
line: the prompt's hash and the reply text. No keys and no personal data: the prompts are the
fictional shop's demo story. They are replayed by `AI_MODE=replay` (the demo video) and by the
hosted demo when its model budget is used up (config/demo.toml).
