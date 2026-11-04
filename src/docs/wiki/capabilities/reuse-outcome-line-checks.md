---
capability: reuse-outcome-line-checks
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_mcp.reuse_outcome.parse_outcomes@9acf747324
  - lupin_mcp.reuse_outcome.unparsed_outcome_lines@119d9a2b7d
  - lupin_mcp.reuse_outcome.is_indexed@7fb4ef6444
  - lupin_mcp.reuse_outcome.token_refusals@535df456bd
  - lupin_mcp.reuse_outcome.log_refusals@e0a61bbd82
  - lupin_mcp.reuse_outcome.pairing_refusals@fddd31904e
  - lupin_mcp.reuse_outcome.missing_outcome_refusals@a6d7d69b8a
---
# Reuse: the REUSE-OUTCOME line and its checks
`lupin_mcp.reuse_outcome` reads the `REUSE-OUTCOME` lines of a review or plan document and checks them. A line ties a lookup to what the diff did with it. The gate that calls it is in [[reuse-merge-gate]]. The run over one whole document, with its record, is in [[reuse-refusals-record]]. It is handed what the log readers return and reads no log itself.

`REUSE-OUTCOME <receipt id> :: <search id> :: REUSED <symbol> | EXTENDED <symbol> | WROTE_NEW <difference> :: <plan path>#<step>`
- `REUSED` and `EXTENDED` take one symbol token and no free text after it. `WROTE_NEW` takes text with no ` :: ` in it.
- The receipt slot is a 16-hex id, `excluded` or `unindexed`. The search slot is `rs-` and ten hex, or `unindexed`.

## Reading
- `parse_outcomes( text )` returns `{ receipt, search, outcome, detail, plan, step, line }` for each matching line, in order. Lines inside a code fence are read like any other. A template line is ignored.
- `unparsed_outcome_lines( text )` returns the lines that open with the keyword, are not the template, and do not match. A line with only one placeholder is listed.

## Checking (each returns `[ { line, reason } ]`)
- `token_refusals` refuses an `excluded` line unless the log holds an `EXCLUDED_` refusal for its first word. It refuses an `unindexed` line unless both slots say `unindexed` and the symbol index does not hold the file.
- `is_indexed( path, root )` says whether the index holds a file, using the indexer's own roots, suffixes and skip rule.
- `log_refusals` refuses a receipt that is not a clean `check_exists` or `fetch_similar` call in the log. It also refuses a search that is not a `record_search` on that receipt. The reason says "not in the log". It warns that a failed log write looks the same.
- `pairing_refusals` requires the outcome kind to pair with a ruling on the same receipt: `DUPLICATE` with `REUSED`, `EXTEND` with `EXTENDED`, `DISTINCT` with `WROTE_NEW`. A receipt no ruling cites is refused.
- `missing_outcome_refusals( added, outcomes, rulings )` returns `{ symbol, reason }` for each new definition with no outcome line. A definition counts as covered through a ruling that cites a receipt an outcome line cites. An `excluded` line covers the symbol it names.
