---
capability: loc-count-classifier
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - scripts.loc-analysis.count.lang_of@f7a5547291
  - scripts.loc-analysis.count.ext_of@537548bc5c
  - scripts.loc-analysis.count.is_test@f4780ca7cf
  - scripts.loc-analysis.count.bucket_of@e103ef3d5d
  - scripts.loc-analysis.count.count_python@1562f6f10c
  - scripts.loc-analysis.count.count_cstyle@58901150b5
  - scripts.loc-analysis.count.count_hash_style@2c2ca1eb97
  - scripts.loc-analysis.count.count_generic@0e904454cc
  - scripts.loc-analysis.count.main@5c1b3ec78e
---
# Lines-of-code counter

Counts the lines of every file that `git ls-files` reports, so ignored build output can never be included. It sorts each file into exactly one bucket, counts code, comment, docstring and blank lines, and writes one JSON row per file. The report that reads those rows is on [[loc-rollup-and-report]].

## Classifying
- `lang_of` names a file's language from its extension, lower-cased. A Dockerfile is recognised by its base name. A file with no extension is `Other (no extension)`, and an unknown extension is `Other`.
- `ext_of` returns the lower-case extension, or an empty string.
- `is_test` is true for a path under `src/tests/` or any `tests` directory, a `test_` file, a file ending `_test.py`, `.test.ts` or `.spec.ts`, and a `conftest.py`.
- `bucket_of` returns a bucket name and whether it is excluded. Exclusion rules run in order and the first match wins. They cover agent output, a vendored Flutter build, minified or vendored JavaScript and lockfiles. They also cover generated API docs, golden snapshots, ephemera, binary assets and data files.
- Next come R&D and history documents, then other documentation, then tests. Everything left is application code and config.

## Counting
- `count_python` tokenizes the text. Any string token that begins a logical line counts as a docstring, on every line it spans, even when code follows it, as in `"abc".upper()`. A comment token counts as a comment. If the text cannot be tokenized, it falls back to a comment-prefix count with no docstrings.
- `count_cstyle` is line-based, for TypeScript, JavaScript and CSS. A block comment opening with `/**` counts as documentation, and any other comment as a comment.
- `count_hash_style` counts lines starting with `#`, `;` or `--` as comments. `count_generic` counts only code and blank lines.
- `main` scans every tracked file and writes the rows to the JSON file named on the command line. A file that cannot be read as UTF-8 is marked binary.
