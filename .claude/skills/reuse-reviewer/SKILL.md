---
name: reuse-reviewer
description: Review a diff for code reuse. For every new definition, fetch its similar existing symbols, read the shortlisted capability pages and source, and rule DUPLICATE, EXTEND <symbol> or DISTINCT <why>, each citing a receipt id. Use in code review of any diff that adds a function, method or class, or when asked "does this already exist?".
---

# Reuse reviewer

Advisory today. The key `reuse review gating` in `src/conf/lupin-app.ini` is `false`, so this
skill reports and never rejects. It rejects only when Rick sets the key to `true` (the recall bar from the baseline run).
Plan: `src/rnd/v0.2.2/2026.09.30-wiki-and-jev-for-code-reuse-review/2026.09.30-reuse-review-implementation-plan.md`, section 8.

## What to do

1. **List the new definitions.** Index the base and the head, then diff them. `--all` includes
   `_private` functions and nested helpers, which the public index skips and where unplanned
   helpers usually live.

   ```bash
   python -m cosa.repo.symindex build --root <tree> --out <dir>      # once per side; note the generation path it prints
   python -m cosa.repo.symindex diff <OLD_GEN> <NEW_GEN> --all > diff.json
   ```

   The new definitions are `added` in `diff.json`. If it holds `algorithm_changed`, rebuild
   both sides with one tool version and diff again. Also treat a `changed` entry whose body
   grew a new nested helper as a new definition.

2. **Ask the index, one definition at a time.** Call `fetch_similar( entry )` with the symbol
   id exactly as `diff.json` lists it. Keep the `receipt_id` it returns. `UNKNOWN_ENTRY` means
   the id is in no definition of the head index, so copy it again from `diff.json`. `_private`
   and nested ids are looked up like public ones.

   An error whose name starts with `EXCLUDED_` means the tool may not send that definition.
   `EXCLUDED_SENSITIVE_CONTENT` is a signature or first docstring line that holds an address,
   path or token. `EXCLUDED_PREFIX` is an id under an excluded prefix. There is no receipt, so
   read the definition and its neighbours yourself and write `excluded` as the receipt token
   in the ruling line.

3. **Read the capability pages** the shortlist points to (`read_capability( names )`). The
   page says the capability's canonical entry point and its "don't" rules.

4. **Read source** only for shortlisted candidates and for any call that returned an `uncertain`
   cause. Rule on source, never on a shortlist line alone, and leave the rest of the tree unread.

5. **Rule**, one line per new definition, in the review document, in this exact shape:

   ```text
   RULING <symbol id> :: DUPLICATE | EXTEND <symbol> | DISTINCT <why> :: reuse-receipt: <receipt id>
   ```

   - `DUPLICATE`: an existing symbol already does this. The diff should call it.
   - `EXTEND <symbol>`: the new code belongs inside that symbol, or should wrap it.
   - `DISTINCT <why>`: you read the candidates' source and name the difference in one clause.

   An assertion without a receipt is challenged. The exit-gate script
   (`src/lupin_mcp/reuse_exit_gate.py`) accepts a ruling only when its receipt is one of the
   receipts logged for that symbol's `fetch_similar` calls.

6. **Run plan 1's linters** on the changed `.py` files and collect their findings:

   ```bash
   python -m cosa.repo.doc_lint.docstring_lint --strict --json <changed .py files>
   ```

   Run `cosa.repo.doc_lint.prose_judge` through its API on the changed docstrings (it makes a
   model call, so it runs here, not in a commit hook).

7. **Report or reject.** Save the findings (linters plus any ruling you challenge) as a JSON
   list and ask the flag:

   ```bash
   python -m lupin_mcp.reuse_review_gate --findings findings.json
   ```

   It prints `mode`. With the flag false the mode is `report-only`: list the findings in the
   review and reject nothing. With the flag true and a finding left, the mode is `reject`.
   Exit code 1 means reject.

## The three vocabularies

One table maps the labels in use, so a receipt cited in a plan's prior-art table needs no translation.

| `check_exists` verdict | `plan-review.md` section 4 prior-art label | Reuse-reviewer ruling |
| --- | --- | --- |
| `REUSE` | `reuse-as-is` | `DUPLICATE` |
| `EXTEND` | `extend-existing` | `EXTEND <symbol>` |
| `NEW` | gen&#117;inely-new | `DISTINCT <why>`, only after the reviewer has read the shortlist's source; a `NEW` verdict does not rule `DISTINCT` by itself |
| `UNCERTAIN_READ_SOURCE` | none yet: read the source first | the reviewer rules only after reading the candidates |

## Rules

- Jev builds shortlists and you rule. Every `DUPLICATE` or `DISTINCT` ruling comes from reading source.
- An `uncertain` cause obliges you to read the candidates. The causes are `LOW_CONFIDENCE`,
  `CALL_FAILED`, `KEY_UNREADABLE`, `DEPENDENCY_MISSING`, `NOT_LUPIN_TREE` and `INDEX_STALE`.
  Treat it as unknown, never as `NEW`.
- A reuse miss is a symbol that should have been on the shortlist and was not.
- Report a miss to the manager as a task-store row with the receipt id and the symbol.
- The counter-reviewer replays your receipts with `replay( receipt_id )`.
- The counter-reviewer also reads the source of any candidate you dismissed.
