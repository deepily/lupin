---
capability: dm-compression-freeze
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.agents.dm_compression.freeze.Span@83591ee128
  - cosa.agents.dm_compression.freeze.Placeholder@bb0db8b4d9
  - cosa.agents.dm_compression.freeze.FrozenMessage@aa40aa4636
  - cosa.agents.dm_compression.freeze.ValidationResult@26c9878cbe
  - cosa.agents.dm_compression.freeze.extract_spans@3017f1798b
  - cosa.agents.dm_compression.freeze.resolve_spans@b37ea6e1e0
  - cosa.agents.dm_compression.freeze.segment_clauses@a6f0fdffdb
  - cosa.agents.dm_compression.freeze.freeze@40ee72201f
  - cosa.agents.dm_compression.freeze.validate@cbe249465b
  - cosa.agents.dm_compression.freeze.restore@a254d035b1
  - cosa.agents.dm_compression.freeze.compress_or_original@586bcfa262
  - cosa.agents.dm_compression.freeze.count_verify_literals@b8b649c1b5
  - cosa.agents.dm_compression.freeze.count_all_literals@ada8b3c2de
  - cosa.agents.dm_compression.corpus_synth.synth_corpus@73f5881785
---
# DM compression freeze protocol

Before a direct message goes to a rewriting model, its exact literals (paths, hashes, URLs, numbers) are swapped for opaque placeholders. After the rewrite they are checked and put back. No model is called here.

## What it does
- `extract_spans` finds every candidate literal as a `Span`. `resolve_spans` reduces overlaps to one set: longest span first, then pattern rank, then leftmost.
- `segment_clauses` splits the text into clause spans that cover it with no gaps. The clause lets a check see a placeholder that moved to another claim.
- `freeze` returns a `FrozenMessage`: the original, the frozen text and one `Placeholder` per occurrence. Identical literals share a group id.
- A message with too many frozen characters or too few compressible words gets a bypass reason. `should_bypass` reports it.
- `validate` checks a rewrite against what was sent and returns a `ValidationResult` with violations and warnings. A moved placeholder is only a warning.
- `restore` puts each literal back with an exact token parser, and the strict form refuses a partial restore.
- `compress_or_original` is the delivery decision. It returns the text to deliver and a fallback reason, and never raises.
- `count_verify_literals` counts the cheap verify-tier literals. `count_all_literals` counts every class in place.
- `synth_corpus` builds a repeatable list of synthetic bodies for tests. The same seed gives the same list, and the hard cases come first.

## Invariants
- Restoring an unmodified frozen text returns the original byte for byte.
- The guarantee is exact preservation of the frozen spans. It does not say the rewrite kept the meaning.
