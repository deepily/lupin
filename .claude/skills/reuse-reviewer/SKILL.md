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
   both sides with one tool version and diff again. A diff that edits the indexer itself
   (`src/cosa/repo/symindex/`, including `ts_extract.js`) always lands here. Use the head
   tree's tool for both sides. Run `build --root <base tree>` from the head checkout, with
   `LUPIN_ROOT` and `PYTHONPATH` pointing at the head tree. Also treat a `changed` entry whose
   body grew a new nested helper as a new definition.

   **The index does not see every file.** A definition in a file outside the index roots is
   never in `added`. In the Lupin tree the script roots are the web tree under
   `lupin_app/static/js`. So `src/cosa/repo/symindex/ts_extract.js` and `src/scripts/*.mjs`
   are not indexed. List those from `git diff <base> <head> -- <file>` by hand. Search the
   tree for a twin with a fixed-string search. Rule with the token `unindexed`, as the
   **Rule** step below describes.

2. **Ask the index, one definition at a time.** Call `fetch_similar( entry, language )` with the symbol
   id exactly as `diff.json` lists it. Pass `language` too: `py`, `ts` or `dart`, the definition's own. The call refuses without it (`LANGUAGE_REQUIRED`). Use `all` only for a deliberate look across languages. Keep the `receipt_id` it returns. Pair it with the symbol you asked about, never with the position of the reply. Parallel calls do not come back in the order they were sent. Run 3 of the W-F crew run matched three receipts to the wrong symbols this way, and the gate answered `WRONG_RECEIPT`. `UNKNOWN_ENTRY` means
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

   **Search the tree for each `DISTINCT` you mean to rule.** The shortlist only covers the index. Call
   `record_search( receipt_id )` with the receipt from the `fetch_similar` call. It makes no model call. It
   searches the working tree for three to six terms and returns the five nearest definitions and a
   `search_id`. Add terms of your own with `extra_terms`. With no receipt, pass `entry` and `language`
   instead. Read the source of each candidate it names. Then write one line per candidate you read, in
   the review document:

   ```text
   SEARCHED <symbol id> :: <search id> :: <candidate id> :: SAME_JOB | RELATED | UNRELATED :: <why>
   ```

   `SAME_JOB` means the candidate already does the work, so the ruling is `DUPLICATE` or `EXTEND`.
   Keep the `RULING` line as it is below; the exit gate does not read the search id yet.

5. **Rule**, one line per new definition, in the review document, in this exact shape:

   ```text
   RULING <symbol id> :: DUPLICATE | EXTEND <symbol> | DISTINCT <why> :: reuse-receipt: <receipt id>
   ```

   One ruling line per symbol, and the symbol id has no spaces or commas. The gate's pattern
   reads `\S+` for the id and `[0-9A-Za-z_-]+` for the receipt. The gate refuses a line that
   opens with `RULING` and does not match, and it names the line.
   For a file outside the index write `<file>#<name>` as the id and `unindexed` as the receipt
   token. The gate only checks ids that are `added`, so it neither accepts nor rejects such a line.
   The reader has to challenge it. Never put free text in the receipt position.

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

   `cosa.repo.doc_lint.prose_judge` makes a model call, so it runs here and not in a commit hook.
   It has no one-call entry point: the module offers `items_from_source`, `changed_items`,
   `parse_findings` and `locate_line`, and the model call itself goes through `harness_runner`
   and `model_transport`. If you cannot assemble that call, write "prose_judge: not run" and the
   reason in the review document; never leave it out silently.

7. **Report or reject.** Save the findings (linters plus any ruling you challenge) as a JSON
   list and ask the flag:

   ```bash
   python -m lupin_mcp.reuse_review_gate --findings findings.json
   ```

   It prints JSON with `mode`, `reject`, `count` and `findings`. With the flag false the mode is
   `report-only`: list the findings in the review and reject nothing. With the flag true and a
   finding left, the mode is `reject`. Exit code 1 means reject. A finding is one object in the
   list; an empty list `[]` is a valid input and answers `report-only`, `count` 0.

## The three vocabularies

One table maps the labels in use, so a receipt cited in a plan's prior-art table needs no translation.

| `check_exists` verdict | `plan-review.md` section 4 prior-art label | Reuse-reviewer ruling |
| --- | --- | --- |
| `REUSE` | `reuse-as-is` | `DUPLICATE` |
| `EXTEND` | `extend-existing` | `EXTEND <symbol>` |
| `UNCERTAIN_READ_SOURCE` | none yet: read the source first | the reviewer rules only after reading the candidates |

`check_exists` no longer returns `NEW` (Rick's ruling of 24 October). A sweep that found nothing is `UNCERTAIN_READ_SOURCE` with the cause `NO_MATCH`: it still names the nearest entries, which you read. `DISTINCT` is only a ruling the reviewer makes after reading those entries; the checker never says `DISTINCT` itself.

## Rules

- Jev builds shortlists and you rule. Every `DUPLICATE` or `DISTINCT` ruling comes from reading source.
- An `uncertain` cause obliges you to read the candidates. The causes are `LOW_CONFIDENCE`,
  `CALL_FAILED`, `KEY_UNREADABLE`, `DEPENDENCY_MISSING`, `NOT_LUPIN_TREE`, `INDEX_STALE` and `NO_MATCH`.
  Treat it as unknown. `NO_MATCH` does not rule `DISTINCT`; read the nearest entries first.
- A reuse miss is a symbol that should have been on the shortlist and was not.
- A receipt for a nested definition (a helper inside a function) has `need_text` in its id. So its id is not the one the plan's id definition gives. A `_private` definition has no such field, because the snapshot holds it.
- The index sha comes from `search_sha`, so it moves when a private definition's signature, pin or docstring changes, as well as a public one.
- Cite the id from the call you made on the final head. An id from an earlier edit still replays, but it describes the older text.
- Report a miss to the manager as a task-store row with the receipt id and the symbol.
- The counter-reviewer replays your receipts with `replay( receipt_id )`.
- The counter-reviewer also reads the source of any candidate you dismissed.

## Counter-reviewer brief

This brief is for the second reviewer. The first reviewer's rulings are claims. You re-run the evidence behind each one and read what the first reviewer set aside. You do not rewrite the rulings. You report where a ruling does not hold.

The plan names this role as an optional counter-reviewer, or as a second reviewer instance given this brief. Spawn it for every review that cites receipts, `EXTEND` rulings included.

### Inputs

- The review document with its `RULING` lines.
- The head tree the review was written against.
- Nothing from the first reviewer's notes. Read the rulings, not the reasoning around them.

### Procedure

1. **Replay every cited receipt.** For each ruling call `replay( receipt_id )` once. A ruling whose receipt token is `excluded` has nothing to replay. Read the definition yourself and go to the `COUNTER` line with `NOTHING_TO_REPLAY`. Read `frozen` and `head` beside `stored`.
   - `frozen` is a re-run against the inputs the receipt recorded. It tests the receipt, not the model.
   - `head` is a re-run against the current tree and index. It tests whether the code or the model still agrees.
   - A difference in `frozen` means the receipt is damaged or was altered. Flag the ruling and stop on that row.
   - A difference in `head` means the answer moved. Note which shortlist entries appeared or left.
   - A named error (`RECEIPT_MISSING`, `RECEIPT_CORRUPT`, `RECEIPT_ID_MISMATCH`, `SNAPSHOT_MISSING`, `SNAPSHOT_CORRUPT`, `CACHE_MISSING`, `CACHE_CORRUPT`) is a finding. It is not a verdict.

2. **Read the dismissed candidates.** Take each symbol on a receipt's `shortlist` or `nearest` that the ruling does not name. Read its source and its capability page. For a `DISTINCT` ruling, check the stated reason against what the candidate does. For a `DUPLICATE` ruling, check that the named symbol is the best of the shortlist.

3. **Look for what the receipt missed.** Search the tree for the operation the new definition performs. This takes one or two fixed-string searches, not a survey. A twin that is in neither the shortlist nor `nearest` is a miss.

4. **Write one line per ruling** in the counter-review document:

   ```text
   COUNTER <symbol id> :: HOLDS | CHALLENGED <why> | UNVERIFIED <cause> | NOTHING_TO_REPLAY :: reuse-receipt: <id>
   ```

   - `HOLDS`: the replay agrees and no dismissed candidate does the job.
   - `CHALLENGED <why>`: a dismissed candidate, or a head difference, changes the ruling. Name the symbol.
   - `UNVERIFIED <cause>`: a named replay error or an unreadable source stopped the check. Give the error name.
   - `NOTHING_TO_REPLAY`: the ruling cites `excluded`, so the tool sent nothing and there is no receipt. It is not a failed check.

5. **Log each miss.** A symbol the receipt should have listed is a miss. Report it to the manager as a task-store row with the receipt id and the symbol. The librarian repairs the wiki from that row.

### Limits

- Replay at `head` makes a model call. Replay the receipts of definitions in dispute first, and the rest after.
- A `HOLDS` line is a statement about the receipt and the candidates you read. It is not a statement about the tree you did not read.
- The counter-reviewer cites its own receipt only for a call it makes. A ruling it challenges keeps the first reviewer's receipt id.
