# Docstring counts outside the swept scope

This page holds the count rule for tracked Python files that are not in the swept scope. The rules and the swept-scope gate are in [docstring-standard.md](docstring-standard.md).

## A count that only falls

Every other tracked Python file (tests, `rnd`, `src/lupin_mcp`) has a count of docstring-lint findings in `src/conf/doc-lint-counts.json`. A file at zero has no entry.

A staged file whose count is above its entry is refused. The refusal prints the count, the entry and up to ten findings, those on lines you touched first. A new file has no entry, so it starts at zero. A renamed file keeps its entry. A copy does not.

Fix it by rewording what you added, or waive a finding on its own line with the same marker as in [docstring-standard.md](docstring-standard.md#waiving-a-finding). An honoured waiver lowers the count. A flat count passes, and so does a finding of one rule traded for one of another.

The table may only fall. A staged table that raises an entry is refused. The one exception is the commit that regenerates the table after a rule change. It carries a new `rules_stamp`, and the table must equal a fresh count of the staged tree. A table cut under other rules refuses any commit that stages a counted file, until it is regenerated. The refusal prints the exact command. The stamp is read from the staged rule files, the ones being committed. A staged edit to a rule file or to the word list makes the table stale.

The findings are counted by the rule code in the working tree. So the gate refuses a commit when any tracked rule file differs between the index and the working tree, and it names the files. The rule files are every tracked file in the `doc_lint` package, the word list and `pre-commit-chain.sh`, read from git at run time. Every run prints how many it compared. Stage the edit with `git add` or restore the file with `git checkout`, then commit again. This holds for swept files, counted files and the table. A commit that stages none of them is not stopped.

A new file beside a deleted counted file may be a rename that git no longer pairs, because too much changed. The refusal says so. Rename the file in one commit and rewrite it in the next. With no table at all, the gate says the scope was not checked.

The run prints `counted scope: N files checked, N at or below their count, N over, N waivers honoured, table ok|stale|absent|regenerated|malformed`.
