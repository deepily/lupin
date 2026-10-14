# Script doc comment standard

This page holds the rules for doc comments in `.ts`, `.js` and `.mjs` files. The Python rules are in [docstring-standard.md](docstring-standard.md).

## What is enforced today

- A JSDoc block gets the text rules that a Python docstring gets. `src/cosa/repo/doc_lint/tsdoc_lint.py` applies them.
- The limits are a summary of 90 characters, a sentence of 25 words and a block of 40 lines.
- A `Design:` path inside the repo must name a file that exists.
- A line or block comment gets a reduced set: the emphasis, tic and history rules. It has no sentence rule and no length rule, so a long line comment passes.
- The line comment at the top of a file also gets the 90-character summary rule. A block comment there does not.
- The docs-only check, not the commit gate, rejects a change to a line comment that starts with `global`, `exported` or `region`.
- The commit gate keeps a count of findings per file in `src/conf/doc-lint-ts-counts.json`. A count may fall and may not rise.
- A count table whose rules stamp is stale refuses every commit that stages an in-scope file.
- If the gate itself crashes, the commit is allowed and the gate prints `GATE CRASHED, commit allowed`.

## What is proposed, not yet enforced

- Every exported symbol has its own JSDoc block. A block above a group covers only the statement that follows it.
- In a `.ts` file, types stay in the signature, not in braces. A `.js` or `.mjs` file keeps its brace types.
- The check that a block exists is not enforced yet. It belongs to the eighth phase of the documentation plan.

## Proving a rewrite changed only comments

`src/cosa/repo/doc_lint/ts_docs_only_diff.py` compares the code tokens of two versions of a script. A commit that changes only comments passes. It also compares directive comments, and the typed tags of a `.js` file. No gate runs it yet.
