---
capability: doc-lint-dart-pairs
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.repo.doc_lint.dart_pairs.block_text@cdeda10efc
  - cosa.repo.doc_lint.dart_pairs.squash@15e9cb05b8
  - cosa.repo.doc_lint.dart_pairs.declaration_name@15d0b40c00
  - cosa.repo.doc_lint.dart_pairs.extract_blocks@187d6aa746
  - cosa.repo.doc_lint.dart_pairs.declarations@07b7b4e015
  - cosa.repo.doc_lint.dart_pairs.comment_prose@53254722f6
  - cosa.repo.doc_lint.dart_pairs.plain_comments@caecd8fe69
  - cosa.repo.doc_lint.dart_pairs.plain_comment_runs@f2b9038ccf
  - cosa.repo.doc_lint.dart_pairs.dart_files@52028ab6c9
  - cosa.repo.doc_lint.dart_pairs.build_pairs@172dcfb2b7
  - cosa.repo.doc_lint.dart_pairs.write_jsonl@55adc54a2a
  - cosa.repo.doc_lint.dart_pairs.main@30dba4cedf
---
# Doc-lint Dart pairs

Builds before and after doc-comment pairs for a Dart git range, one per documented symbol. The pool builder that reads the same blocks is [[doc-lint-dart-pool-builder]].

## Reading doc blocks
- `extract_blocks` lists each doc block with the symbol it documents, as `Owner.member` or a bare name. A repeat gets `#2`, `#3`, and a block with no readable declaration is `<unattached>`.
- `declaration_name` names the identifier a declaration introduces. `declarations` lists member-level declarations whether or not a comment sits above them.
- `block_text` strips trailing white space and edge blank lines, keeping inner indentation. `squash` reduces text to its words for an unchanged check.
- `plain_comment_runs` maps each declaration to the `//` comment just above it, with the lines dropped. `comment_prose` drops tool directives and task markers, and `plain_comments` keeps the non-empty text.

## Pairs
- `dart_files` lists tracked `.dart` files under a prefix at a revision, from git. `build_pairs` pairs each old block of enough words with the new block of the same file and symbol.
- A symbol whose block is gone but whose declaration remains pairs with its plain comment, or with an empty string. A pair that differs only in white space is dropped unless unchanged pairs are included.
- The report counts every pair not made and why, so a drop is never silent.
- `write_jsonl` writes the pairs one per line. `main` writes `--out` when given and prints the report as JSON.
