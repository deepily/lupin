---
capability: doc-lint-text-rules
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.repo.doc_lint.text_rules.line_of_offset@925672db9f
  - cosa.repo.doc_lint.text_rules.summary_findings@3622c7c291
  - cosa.repo.doc_lint.text_rules.preface_findings@f1311659ee
  - cosa.repo.doc_lint.text_rules.prose_lines@271712bb62
  - cosa.repo.doc_lint.text_rules.sentence_findings@d31b965bbd
  - cosa.repo.doc_lint.text_rules.emphasis_findings@056b68cb4c
  - cosa.repo.doc_lint.text_rules.rhetoric_findings@8b82b94ae3
  - cosa.repo.doc_lint.text_rules.defined_labels@2e133170e1
  - cosa.repo.doc_lint.text_rules.defined_steps@d52d3f3897
  - cosa.repo.doc_lint.text_rules.is_config_key_match@00cb0287ca
  - cosa.repo.doc_lint.text_rules.reference_findings@70287f5078
  - cosa.repo.doc_lint.text_rules.contract_item_lines@9a4668a8b9
  - cosa.repo.doc_lint.text_rules.do_not_starts@ee26acbb5a
  - cosa.repo.doc_lint.text_rules.history_findings@4855a8dc13
  - cosa.repo.doc_lint.docstring_lint.is_tool_registered@483ca51054
  - cosa.repo.doc_lint.docstring_lint.extract_docstrings@cb86fa3455
  - cosa.repo.doc_lint.docstring_lint.lint_source@34bd600757
  - cosa.repo.doc_lint.docstring_lint.main@5fb87f64a2
---
# Doc-lint text rules

The writing rules shared by the Python, Dart and markdown linters, and the Python docstring linter that applies them. Each rule returns `Finding` rows at a file line.

## Rules in `text_rules`
- `summary_findings` flags a first paragraph, with wrapped lines joined, over the summary cap. `preface_findings` flags prose before the first `Requires`, `Ensures` or `Raises` header that runs over the preface cap. `sentence_findings` flags a sentence over the word cap, after joining wrapped lines.
- `prose_lines` yields the prose lines of a docstring or page, skipping contract sections, bullets in docstrings, headings and table rows. `contract_item_lines` and `line_of_offset` locate lines for the rules.
- `emphasis_findings` flags capitalised emphasis words and emphasis glyphs. `rhetoric_findings` flags frozen tic phrases, except inside inline code in markdown.
- `reference_findings` flags a reference with no path, such as a bare section mark or row id. `defined_labels` and `defined_steps` collect labels a text defines itself, and `is_config_key_match` skips a match inside an INI key.
- `history_findings` flags dated banners, calendar dates and orders aimed at a model. `do_not_starts` finds sentences that open with "Do not".

## Python docstrings
- `extract_docstrings` returns each docstring with the file line of its first line.
- `lint_source` lints every docstring of one file. A file that does not parse gives one parse-error finding, and a dead `Design:` path inside the root gives a finding.
- `is_tool_registered` finds an MCP tool by its `tool` decorator, so the tool's docstring is exempt from the shape rules. `main` runs the linter through `cli.run_linter`.

Related: [[doc-lint-gate]], [[doc-lint-support-modules]].
