---
capability: utils-review-verdict-gate
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.utils.review_verdict.last_summary_counts@1e56847ddf
  - cosa.utils.review_verdict.parse_census@a9b41687f3
  - cosa.utils.review_verdict.require_clean_for_merge@c6baa25531
  - cosa.utils.review_verdict.verdict_line@53cfd6c3da
  - cosa.utils.review_verdict.check_line@fccae14a79
  - cosa.utils.review_verdict.main@4c58de84d5
---
# Review verdict gate

A reviewer ends a review with one line that names the tree, the census-guard result and Merge or Fix. The merger checks that line before merging. `src/scripts/review-verdict.sh` is the command line; the code is `cosa.utils.review_verdict`. The census guards themselves are run by `src/tests/run-census-guards.sh`.

## What it does
- `last_summary_counts( text )` reads the pass, fail and error counts from the last whole pytest summary line (`N passed, … in Ts`). It returns `None` when there is none. A test name such as `5 passed` is not a summary line, so it cannot count. `cosa.agents.swe_team.test_runner` uses it too.
- `parse_census( text )` reads the tree sha from the first `[tree-state]` line and the pass, fail and error counts from the last pytest summary line. It raises `ValueError` when either is missing, so a run that printed no tree or no summary proves nothing.
- `require_clean_for_merge( verdict, passed, failed, errors )` raises `ValueError` for Merge over a census with no passed tests, or with any failure or error.
- `verdict_line( head, census, verdict )` builds `REVIEW-VERDICT sha=<12 hex> census=<p>p/<f>f/<e>e verdict=<Merge|Fix>`. It refuses a verdict other than Merge or Fix, a census run on another tree, and Merge over a red census.
- `check_line( line, head )` is the merger's side. It refuses a line with no census count, a line for another sha, and Merge over a red census. Otherwise it returns the parsed fields.
- `main( argv )` prints the verdict line for HEAD (`--verdict Merge|Fix`, running the census or reading `--census-log`) or checks a line (`--check`). It returns 0 after printing, and 2 after printing `review-verdict: refused: <cause>`. Building a verdict refuses a tree with tracked changes, because the census would describe other bytes.

## Don't
- Don't give a verdict from a census run on a different sha. The line carries the sha so the merger can tell.
