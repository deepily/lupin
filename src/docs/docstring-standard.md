# Docstring standard

The eight writing rules are not in this page yet. It covers only what the commit gate does.

Scripts: see [script-doc-comment-standard.md](script-doc-comment-standard.md).

The rules are in code. `src/cosa/repo/doc_lint/text_rules.py` holds the text rules. `src/cosa/repo/doc_lint/rule_lists.py` holds the limits: summary 90 characters, sentence 25 words, preface 6 lines, docstring 40 lines. This page covers only what the commit gate does with them.

## The commit gate now refuses

`src/scripts/pre-commit-chain.sh` runs `src/cosa/repo/doc_lint/gate.py` on every commit.

A staged Python file in the swept scope that holds one or more docstring-lint findings, on any line and from any rule, is refused. The gate exits 3 and the chain stops the commit. A refusal prints the file, the line, the rule, the text on that line, where the text belongs, and the waiver form.

The swept scope is defined once, in `swept_scope.is_swept`. It is a `.py` path that `cli.in_scope` accepts. That excludes `tests/`, `rnd/`, vendored trees, `test_*` files and `conftest.py`. It also excludes `src/lupin_mcp/`. Python outside it is held to a count, below.

The chain runs the gate with `--blocking`. A finding on a line the commit touches is refused too, whichever linter reports it: docstrings, `#` comments, ruff, markdown and markdownlint. It prints as a `REFUSED` line and the gate exits 3. Fix the line, stage the fix and commit again.

Three markdown rules judge the whole page: `capability-length`, `reference-length` and `runbook-template`. They apply when a commit edits the page, deletes lines from it, or moves it to another path without an edit. Such a finding refuses the commit only when the commit created the condition. That means the page is new, or the last commit's copy did not have the finding, or the measured value rose. The last commit's copy is judged under the path it had then. A page moved to a path that brings a limit is therefore refused, whether or not the move edits it. A page moved between two paths under the same limit is not. A condition the last commit already had prints with `this condition predates the commit` and the commit goes through. So does an edit that shortens a page that is still over its limit.

A ruff finding is waived with ruff's own `# noqa: <code>`. A docstring finding is waived with the marker described below. A markdown finding and a `#` comment finding cannot be waived. A marker that waives a docstring finding does not cover a comment finding on the same line.

Concluding a conflicted merge or cherry-pick is a special case. Some findings sit on a line that is identical in the commit being merged or picked. Such a finding is printed with `this line came in with the merged or picked commit`. It does not refuse the commit. A line you changed while resolving the conflict is held like any other. A revert gets no such treatment. If the gate cannot read git's record of the incoming commit, it prints a warning and enforces every finding.

The range gate (`range_gate.py`) replays the commits of a range under these rules. It holds a commit to blocking only when its parent descends from the sha in `src/conf/doc-gate-blocking-epoch.txt`. A range is judged under the value its base records. The head of the range must record the same value. A head that records another value, no value or no file stops the run with exit 2, and the line names both. When the base records no value, as in the range that lands the epoch, the head's value is used. The working copy of the file must record the same value as the head.

The range gate replays a merge commit with its other parents as the incoming commit. A line that came in unchanged with the merged commit is not enforced, as at the hook. A concluded cherry-pick is different. Git keeps no record of the commit it picked, so the replay cannot recognise it. It is replayed as an ordinary commit, and a finding the hook let through as picked is refused on replay. Fix the line, or land the commit by a merge.

Five record locations stay in warn mode: the root `history.md`, `TODO.md`, `bug-fix-queue.md`, `history/` and `todo-history/`. Their findings print with `(warn mode, commit allowed)`. The same name elsewhere is held like any page.

If the gate itself crashes, it prints `GATE CRASHED, commit allowed` and the commit goes through. The gate may also end with an exit other than 0 or 3. The chain then prints `doc-lint gate exited N without a refusal verdict, commit ALLOWED` and the commit goes through. That covers a gate that cannot start, a killed gate, and a tree whose `gate.py` predates blocking and exits 1 on a finding. Findings printed above that line were not enforced; rebase such a tree.

Every run prints the denominator: `swept scope: N files checked, N docstrings checked, N findings, N waivers honoured, N unparsed, N undecodable`. A swept file that does not parse is refused and counted as unparsed. A swept file that is not UTF-8 is refused and counted as undecodable. No waiver covers either. A leading byte-order mark is ignored. Any other file that is not UTF-8 is skipped with a warning.

A staged gitlink, which is a submodule entry, holds no text. The gate prints that it was not checked. A file whose name is not UTF-8 is still checked by the gate's own rules, by ruff and by the TypeScript count. Markdownlint cannot be given such a name, or one with a line break. When it is installed, the gate refuses that file. Rename it. In a Python file whose lines end in a bare carriage return, every line counts as touched. If that refuses a merge, convert line endings while resolving or fix the findings.

## Waiving a finding

End the line the finding sits on with:

```text
doc-lint: waive <rule> -- <reason>
```

The rule must be the one the refusal named. The reason must hold a word of three letters or more; `-`, `n/a` and `ok` do not count. A marker without a reason waives nothing, and the refusal says so. A marker naming another rule, or sitting on another line, waives nothing. For a one-line docstring the marker can follow the closing quotes.

Use a waiver when the lint is wrong about this text, not to skip the rewrite. The gate prints how many waivers it honoured on every run.

## Files outside the swept scope: a count that only falls

Every other tracked Python file (tests, `rnd`, `src/lupin_mcp`) has a count of docstring-lint findings in `src/conf/doc-lint-counts.json`. A file at zero has no entry.

A staged file whose count is above its entry is refused. The refusal prints the count, the entry and up to ten findings, those on lines you touched first. A new file has no entry, so it starts at zero. A renamed file keeps its entry. A copy does not.

Fix it by rewording what you added, or waive a finding on its own line with the same marker as above. An honoured waiver lowers the count. A flat count passes, and so does a finding of one rule traded for one of another.

The table may only fall. A staged table that raises an entry is refused. The one exception is the commit that regenerates the table after a rule change. It carries a new `rules_stamp`, and the table must equal a fresh count of the staged tree. A table cut under other rules refuses any commit that stages a counted file, until it is regenerated. The refusal prints the exact command. The stamp is read from the staged rule files, the ones being committed. A staged edit to a rule file or to the word list makes the table stale.

The findings are counted by the rule code in the working tree. So the gate refuses a commit when any tracked rule file differs between the index and the working tree, and it names the files. The rule files are every tracked file in the `doc_lint` package, the word list and `pre-commit-chain.sh`, read from git at run time. Every run prints how many it compared. Stage the edit with `git add` or restore the file with `git checkout`, then commit again. This holds for swept files, counted files and the table. A commit that stages none of them is not stopped.

A new file beside a deleted counted file may be a rename that git no longer pairs, because too much changed. The refusal says so. Rename the file in one commit and rewrite it in the next. With no table at all, the gate says the scope was not checked.

The run prints `counted scope: N files checked, N at or below their count, N over, N waivers honoured, table ok|stale|absent|regenerated|malformed`.
