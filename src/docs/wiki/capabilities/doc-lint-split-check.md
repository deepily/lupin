---
capability: doc-lint-split-check
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.repo.doc_lint.split_check.non_blank_lines@084c8caa8d
  - cosa.repo.doc_lint.split_check.move_targets@7cdf72e3b9
  - cosa.repo.doc_lint.split_check.expected_lines@b3803d4ffd
  - cosa.repo.doc_lint.split_check.targets_of@2703d5e118
  - cosa.repo.doc_lint.split_check.github_slug@66297f5914
  - cosa.repo.doc_lint.split_check.structure_counts@b6b3d1c750
  - cosa.repo.doc_lint.split_check.heading_homes@ead3757b5a
  - cosa.repo.doc_lint.split_check.unresolved_anchors@cdd660929e
  - cosa.repo.doc_lint.split_check.repoint_back@ac18d1de35
  - cosa.repo.doc_lint.split_check.dangling_in@bfa24f1eea
  - cosa.repo.doc_lint.split_check.part_rows@0d16cf8cf6
  - cosa.repo.doc_lint.split_check.compare@8c6e996a4f
  - cosa.repo.doc_lint.split_check.read_old@a969c9b67a
  - cosa.repo.doc_lint.split_check.read_new@fda250f696
  - cosa.repo.doc_lint.split_check.check_split@8902c5072c
  - cosa.repo.doc_lint.split_check.format_report@2e95275332
  - cosa.repo.doc_lint.split_check.main@481ba46e58
---
# Doc-lint split check

Checks that a page cut into an index and numbered parts keeps every non-blank line of the old page, once. It reads the old page from a revision and the new files from the tree or a revision.

## Expected form
- `non_blank_lines` numbers the non-blank lines with trailing white space removed. `expected_lines` gives each old line the form it takes in a part: unchanged inside a code fence, otherwise through `move_targets`.
- `move_targets` adds `../` to each relative link target outside a code span, except a scheme, `#` or `/` target. `targets_of` lists the link targets of a line.
- `part_rows` numbers a part's non-blank lines with whether each sits in a fence.

## Anchors
- `github_slug` approximates the anchor GitHub makes from a heading. `heading_homes` maps each old anchor to the part file and anchor that now hold the heading, numbering repeats as the old page did.
- `repoint_back` undoes an allowed in-page repoint, from `F.md#y` to `#x`. `dangling_in` lists in-page links that would break in the part that holds them.
- `unresolved_anchors` lists links whose heading is in no part. They are listed and never failed, since the split did not make them.

## Comparing
- `compare` returns the lines dropped, doubled, unmoved and dangling, with the moved targets. `structure_counts` counts table rows, fences, headings and link targets.
- `read_old` and `read_new` read a page at a revision or from the tree. `check_split` returns `compare`'s result and a refusal with a message when a file or revision is unreadable.
- `format_report` leads with the verdict. `main` exits 0 when nothing is lost, 1 when a line is dropped, doubled, unmoved or dangling, and 2 on a refusal.
