---
capability: doc-lint-reader-run-text
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.repo.doc_lint.reader_rig_run.RunRefused@1a99858d78
  - cosa.repo.doc_lint.reader_rig_run.parse_args@e2c2e4a8d0
  - cosa.repo.doc_lint.reader_rig_run.load_questions@a833e77fa3
  - cosa.repo.doc_lint.reader_rig_run.check_prefix@6876a45537
  - cosa.repo.doc_lint.reader_rig_run.rig_questions@5bfb590d0e
  - cosa.repo.doc_lint.reader_rig_run.group_by_file@abe1723592
  - cosa.repo.doc_lint.reader_rig_run.resolve_rev@ef8a9f56e6
  - cosa.repo.doc_lint.reader_rig_run.read_at@d114aadc78
  - cosa.repo.doc_lint.reader_rig_run.signature_line@74ef7ff020
  - cosa.repo.doc_lint.reader_rig_run.extract_doc_text@95034757dc
---
# Doc-lint reader run text

The input half of the reader-test command line: fixed questions over a file at two revisions. The reader sees documentation text only, never code bodies. Scoring is in [[doc-lint-reader-run-scoring]].

## Questions
- `load_questions` reads the questions file and returns the questions with the sha256 of its bytes. The file's own count must equal the number of questions.
- `rig_questions` keeps `id`, `question` and one key string, the `key_points` joined with a semicolon and a space. The wrong-answer, verified, symbols and file fields are dropped.
- `group_by_file` groups questions by their file, in the order first seen.
- `check_prefix` refuses a file prefix that could leave the repository, an absolute one or one holding a `..` part.

## Reading the file
- `resolve_rev` returns the full sha a revision names. `read_at` returns a file's text at a commit, read from git and never from the working tree.
- `extract_doc_text` builds the text a reader may use: the module docstring, every `#` comment line, and the signature then docstring of each class and function. Nested ones count, code bodies do not, and both revisions get the same extraction.
- `signature_line` renders a class or function signature on one line with no decorators and no body.

## Command line
- `parse_args` requires the models, the ledger and both caps, with no default. `--runs` defaults to 3.
- `RunRefused` is raised when the run cannot start, and its message names why.
