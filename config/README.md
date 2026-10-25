# config

Dated configuration: model names, prices, thresholds, and solver weights (hard rule 8: config, not memory).

Rules:
- Each file states the date it was last checked and the source (for example, the provider docs page for a model name).
- Code reads values from here. No model names, prices, or weights are hard-coded elsewhere.
- No secrets. Secrets go in `.env` (see `.env.example`).
