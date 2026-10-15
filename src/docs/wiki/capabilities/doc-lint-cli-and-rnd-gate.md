---
capability: doc-lint-cli-and-rnd-gate
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.repo.doc_lint.cli.split_names@7d521082b5
  - cosa.repo.doc_lint.cli.crosses_as_text@4aef2840d2
  - cosa.repo.doc_lint.cli.split_lines@c2cd21f2ab
  - cosa.repo.doc_lint.cli.line_text@1e012ed20f
  - cosa.repo.doc_lint.cli.shown@650d4426e1
  - cosa.repo.doc_lint.cli.tracked_files@9d4887c58a
  - cosa.repo.doc_lint.cli.build_parser@99822c5036
  - cosa.repo.doc_lint.rnd_gate0.is_rnd@b7ed570571
  - cosa.repo.doc_lint.rnd_gate0.rnd_population@3d66963a32
  - cosa.repo.doc_lint.rnd_gate0.rnd_markdown@d153a2a051
  - cosa.repo.doc_lint.rnd_gate0.gate0@e8f7bb21c2
  - cosa.repo.doc_lint.rnd_gate0.citer_kind@f137b8ec09
  - cosa.repo.doc_lint.rnd_gate0.resolve@6e6a0da3ac
  - cosa.repo.doc_lint.rnd_gate0.describe@3659d8b0e8
  - cosa.repo.doc_lint.rnd_gate0.precedent_violations@d5381af600
  - cosa.repo.doc_lint.rnd_gate0.main@73a099e0f7
---
# Doc-lint command line and R&D gate

The command-line helpers the linters share, and Gate 0 of the R&D triage, which stops a document a live file cites from being called history.

## Shared driver (`cli`)
- `build_parser` builds the parser every linter shares: optional paths, `--changed`, `--staged`, `--strict`, `--json` and `--repo-root`.
- `tracked_files` lists git-tracked files with a suffix, in scope only unless `scoped` is false. With `links` set it lists only symbolic links.
- `split_names` reads a `-z` git listing and keeps each name's bytes, even when it is not UTF-8. `crosses_as_text` is false for a name a UTF-8 tool would replace with another.
- `split_lines` splits a source the way its parser numbers lines, so a bare carriage return ends a line. `line_text` returns one numbered line, or an empty string past the end.
- `shown` makes a name safe to print on one line. A non-UTF-8 byte becomes `\xNN` and a control character its backslash escape.

## Gate 0 (`rnd_gate0`)
- `is_rnd` is true under `src/rnd/` or `src/cosa/rnd/`. `rnd_population` lists every tracked file there and `rnd_markdown` its `.md` members.
- `gate0` searches every tracked file for citations of each document. A citer lands in the strongest class it matches by path, name or stem, and `blocks_history` says whether a live one holds the document.
- `citer_kind` puts a citing file in a category: archive, index, rnd, decision or live. `resolve` settles each document's final class, and a document proposed as history becomes `new` when a citer holds it.
- `describe` counts the holding and passing citers by category in one line. `precedent_violations` lists documents that still came out as history.
- `main` prints a TSV of the verdicts, or the full mapping with `--json`.
