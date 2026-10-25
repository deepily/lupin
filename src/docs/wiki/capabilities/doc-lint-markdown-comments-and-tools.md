---
capability: doc-lint-markdown-comments-and-tools
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.repo.doc_lint.md_lint.blank_fences@90b46154af
  - cosa.repo.doc_lint.md_lint.blank_non_prose@7e3671f614
  - cosa.repo.doc_lint.md_lint.template_findings@8daf7fa45d
  - cosa.repo.doc_lint.md_lint.sibling_paths@c3d0846f6e
  - cosa.repo.doc_lint.md_lint.sibling_resolved@7e0007822e
  - cosa.repo.doc_lint.md_lint.lint_source@dd8cbd5553
  - cosa.repo.doc_lint.md_lint.page_rates@686541f8c2
  - cosa.repo.doc_lint.md_lint.main@3d4c1e198a
  - cosa.repo.doc_lint.comment_lint.lint_source@781bc9f4b5
  - cosa.repo.doc_lint.comment_lint.main@cf9a3c5ee4
  - cosa.repo.doc_lint.tool_runners.Unchecked@b434e70fc0
  - cosa.repo.doc_lint.tool_runners.find_tool@233a01621a
  - cosa.repo.doc_lint.tool_runners.missing_tool_warning@667c90f9a6
  - cosa.repo.doc_lint.tool_runners.run_ruff@662ef662ae
  - cosa.repo.doc_lint.tool_runners.unnamed_warning@7a7e1b7a53
  - cosa.repo.doc_lint.tool_runners.markdownlint_unnamed@d1859a93be
  - cosa.repo.doc_lint.tool_runners.run_markdownlint@ef34ff9619
  - cosa.repo.doc_lint.tool_runners.run_dart_analyze@9f142b93d3
---
# Doc-lint markdown, comment and tool runners

The markdown linter, the `#` comment linter and the runners for the external tools the [[doc-lint-gate]] calls.

## Markdown (`md_lint`)
- `lint_source` lints one page with the [[doc-lint-text-rules]] and the link check, not reading front matter or fenced code as prose. `blank_fences` and `blank_non_prose` blank those blocks and keep the line count.
- `template_findings` caps a capability page by lines and a reference page by words. A runbook-named page must carry the runbook sections.
- `sibling_paths` lists the other parts of a split page, an index `foo.md` plus numbered files in `foo/`. `sibling_resolved` drops a bare-ref finding that a sibling defines.
- `page_rates` returns marker rates per thousand words, and `main` runs the linter through `cli.run_linter`.

## Comments (`comment_lint`)
- `lint_source` checks every `#` comment for banners, shouting and emphasis glyphs. It skips the shebang and reports one parse-error finding for a file that cannot be tokenized. `main` is its entry point.

## Tool runners (`tool_runners`)
- `find_tool` returns an env override, a candidate under the root, or the name on the search path, else `None`. `missing_tool_warning` builds the loud skipped-check line.
- `run_ruff` and `run_markdownlint` return findings and warnings. A missing tool gives one warning. An exit above 1 gives an `Unchecked` warning, which the blocking gate refuses on.
- `markdownlint_unnamed` lists names the tool cannot read back, and `unnamed_warning` says such a file was not checked. `run_dart_analyze` keeps only documentation diagnostics.
