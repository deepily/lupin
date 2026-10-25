---
capability: router-label-audit
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - scripts.router_label_audit.unit_tokens@a82bf30105
  - scripts.router_label_audit.unit_categories@c38c8274f5
  - scripts.router_label_audit.classify_bucket@7c7e8525ff
  - scripts.router_label_audit.destination_capability@cae1583335
  - scripts.router_label_audit.destination_arithmetic@883a4436de
  - scripts.router_label_audit.is_calculator_shaped@0985b41d3e
  - scripts.router_label_audit.is_math_shaped@360fa21fb0
  - scripts.router_label_audit.read_utterances@af8e3ab761
  - scripts.router_label_audit.duplicate_check@8fdcdfa48e
  - scripts.router_label_audit.recount_cold@4ddc630391
  - scripts.router_label_audit.main@cd17200e11
---
# Router label audit

A router training-label audit and line-by-line move tool. It sorts every utterance in the math-agent training file into three buckets and assigns a destination label under a named rule. It also checks for duplicates against the calculator file, and writes an audit CSV so a reviewer can refute each call. The caller names the rule, and the CSV records which one produced the destinations.

## Buckets
- `unit_tokens` returns the canonical unit names the calculator's own tables recognise in a text. Plural forms are folded, multi-word names resolve first, and tokens that are also ordinary words are excluded. It is the one tokenizer, so a fix cannot leave one rule behind.
- `unit_categories` returns the conversion categories a set of unit tokens belongs to.
- `classify_bucket` assigns one of four labels: bare arithmetic, symbolic, word problem or routing phrase. A blank line raises `ValueError`. The assignment is a keyword heuristic, not a measurement.

## Rules
- `destination_capability` labels an utterance `calculator` only if it maps to convert, compare prices or mortgage. Everything else, bare arithmetic included, stays `math`. This rule is stale, because the calculator now also has an arithmetic operation, and it is left unchanged.
- `destination_arithmetic` sends bare arithmetic and the four-operation half of the word problems to the calculator. A formula, rate, unit conversion or unknown keeps an item in `math`.
- Both return the label and a reason. `is_calculator_shaped` and `is_math_shaped` return true only on a positive match, never by a default.

## Corpus work
- `read_utterances` returns the line number and text of content lines, skipping blanks and comments.
- `duplicate_check` reports proposed movers already in the calculator file, and duplicates within the movers.
- `recount_cold` recomputes cold-pass routing accuracy on the math-expected set under new labels, from a paired eval's records file. It applies no interpretive rule to the router's output.
- `main` runs the audit. `--apply` moves the lines, and `--audit-csv` writes the CSV.
