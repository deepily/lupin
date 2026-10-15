---
capability: doc-lint-page-pairs-and-loader
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.repo.doc_lint.page_pairs.split_sections@15545d3927
  - cosa.repo.doc_lint.page_pairs.chunk_text@6ca6d6fef7
  - cosa.repo.doc_lint.page_pairs.page_pairs@538cbdbd68
  - cosa.repo.doc_lint.page_pairs.join_new_text@e774db7db4
  - cosa.repo.doc_lint.page_pairs.read_at@935056a8d5
  - cosa.repo.doc_lint.page_pairs.build_pairs@0705267e5d
  - cosa.repo.doc_lint.page_pairs.main@5be716596e
  - cosa.repo.doc_lint.labelled_pairs.load_pairs@87dd9573e2
  - cosa.repo.doc_lint.labelled_pairs.refuse_gate_path@f98a3d07fe
---
# Doc-lint page pairs and pair loader

Whole-page before and after texts cut into chunks the claim harness can read, and the loader that joins a labelled pairs file to its keys. The harness is [[doc-lint-harness-runner]].

## Page pairs (`page_pairs`)
- `split_sections` cuts a page at its second and third level headings, never inside a fenced block. The sections join back to the exact text.
- `chunk_text` groups consecutive sections into chunks of about the target word count. A section is never cut, and a longer one is a chunk of its own.
- `page_pairs` builds one `{ id, old, new }` per chunk of the old text. Every pair carries the whole new text, and ids add `#` and a three digit counter.
- `join_new_text` joins a new page's files under a header line naming each path. `read_at` reads a file at a revision, or returns `None` when absent.
- `build_pairs` builds the pairs of every page in a manifest, old text at `old_ref` and new at `new_ref`. A missing path raises `ValueError`.
- `main` reads a manifest and writes the pairs file with `--out`.

## Pair loader (`labelled_pairs`)
- `load_pairs` joins a pairs file and its keys file into `{ id, old, new, design, seed_span }`. The ids must match one to one, and a repeated id raises `ValueError`.
- A seed span is set only for a seeded positive, and it must occur exactly once in the old text. A relocated claim is not a seeded removal.
- `refuse_gate_path` refuses a path with a component `gate` or starting `gate-`. It checks the written path and its real path, so a symlink cannot reach a gate file.
