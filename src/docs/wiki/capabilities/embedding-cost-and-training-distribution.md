---
capability: embedding-cost-and-training-distribution
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - scripts.v2_embedding_cost.summarize@7cfc2e7ba5
  - scripts.v2_embedding_cost.measure@e7f46c7bc4
  - scripts.v2_embedding_cost.format_report@ee96d8171e
  - scripts.v2_embedding_cost.main@dac9d7dca3
  - scripts.analyze-training-distribution.categorize_command@71b93905ba
  - scripts.analyze-training-distribution.print_separator@e6de43c1ad
  - scripts.analyze-training-distribution.main@79a72459d2
---
# Embedding cost and training distribution

Two measurement command lines for the model work. Neither needs a GPU. The first needs a live authenticated server, and the second reads local files only.

## Embedding cost
- The embedding-cost script asks how expensive it is to embed a query on the tier-2 similar path. It also asks how much the verbatim embedding cache saves on a warm repeat. A generated embedding is a round trip to the model server. A cached one is a lookup only.
- `summarize` returns the count, mean, median, 95th percentile, minimum and maximum of a list of millisecond timings, by nearest rank. An empty list raises `ValueError`.
- `measure` runs each question cold, then warm, through a probe function. It returns per-question rows and a summary of the generated timings. It adds a summary of the cached timings and the speedup, the generated mean over the cached mean.
- A warm call that reported no cache hit is left out of the cached summary. Only real hits count toward the saved cost.
- `format_report` renders the result as a markdown table with a headline line.
- `main` takes `--live` and extra `-q` questions. Without `--live` it only says it is the instrument. The measurement runs on the scheduled `:8000` venue, never `:7999`.

## Training distribution
- `categorize_command` puts a command string into Agent Router, Browser Search, Browser Navigation or Other.
- `print_separator` prints a separator line of a given character and width.
- `main` loads the voice-command JSONL training data and prints a file inventory, per-command sample counts, category breakdowns and summary statistics.
