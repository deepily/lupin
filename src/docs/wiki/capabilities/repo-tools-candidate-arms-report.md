---
capability: repo-tools-candidate-arms-report
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.repo.symindex.candidates.arm_report.count_redactable@ebeb7e374b
  - cosa.repo.symindex.candidates.arm_report.percent@f39092c4de
  - cosa.repo.symindex.candidates.arm_report.size@f299d01cbf
  - cosa.repo.symindex.candidates.arm_report.render_report@1274766364
  - cosa.repo.symindex.candidates.arm_report.write_report@2d5e50a772
---
# Candidate arms: the results page

`arm_report.py` builds the final comparison page from numbers the caller measured. It reads no cache, no needs file and no index.

## Building the page
- `render_report( meta, t1, t3, t2, vectors_choice, fusion, redactable )` returns the markdown. It opens with the run id, five shas, the winning vector arm and the fusion constants, then gives three tables and a redaction line.
- T1: recall of the full-sweep shortlist.
- T3: where the known twin lands.
- T2: replayed verdicts.
- Redaction: how many needs hold a redactable token.
- The page says every figure is in-sample and is not a flip rate.
- `meta` must hold every key in `META_KEYS`: `run_id`, `code_sha`, `index_sha`, `manifest_hash`, `needs_sha`, `cache_sha`. A missing or empty one raises `REPORT_META_MISSING` naming the keys.
- `write_report( path, text )` makes the folder if needed, writes UTF-8 and returns the sha256 of the bytes written.

## Helpers
- `percent( value )` formats a share as `12.3%`, or `-` for `None`. `size( value )` formats a mean shortlist size with no decimals, or `-`.
- `count_redactable( needs, redactor, planted_text )` counts the needs for which the redactor reports a span.
- It returns the count, the sorted ids, the number of needs and a `control` flag. The flag is true only when the redactor finds a span in `planted_text`. A redactor that finds nothing therefore shows up.
- The partial page in [[repo-tools-candidate-arms-measure]] reuses `percent`, `size`, `META_KEYS` and `write_report`.
