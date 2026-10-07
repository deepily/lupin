# Docstring standard

The eight writing rules are not in this page yet. It covers only what the commit gate does.

The rules are in code: `src/cosa/repo/doc_lint/text_rules.py` holds the text rules and `src/cosa/repo/doc_lint/rule_lists.py` holds the limits (summary 90 characters, sentence 25 words, preface 6 lines, docstring 40 lines). This page covers only what the commit gate does with them.

## The commit gate now refuses

`src/scripts/pre-commit-chain.sh` runs `src/cosa/repo/doc_lint/gate.py` on every commit.

A staged Python file in the swept scope that holds one or more docstring-lint findings, on any line and from any rule, is refused. The gate exits 3 and the chain stops the commit. A refusal prints the file, the line, the rule, the text on that line, where the text belongs, and the waiver form.

The swept scope is defined once, in `swept_scope.is_swept`: a `.py` path that `cli.in_scope` accepts (not under `tests/` or `rnd/`, not a vendored tree, not a `test_*` file or `conftest.py`) and not under `src/lupin_mcp/`. Everything outside it stays in warn mode: findings on staged lines are printed and the commit goes through. That covers tests, `src/lupin_mcp`, `rnd`, markdown, `history.md` and `TODO.md`.

If the gate itself crashes, it prints `GATE CRASHED, commit allowed` and the commit goes through.

Every run prints the denominator: `swept scope: N files checked, N docstrings checked, N findings, N waivers honoured, N unparsed`. A swept file that does not parse is refused and counted as unparsed; no waiver covers it. A leading byte-order mark is ignored.

## Waiving a finding

End the line the finding sits on with:

```text
doc-lint: waive <rule> -- <reason>
```

The rule must be the one the refusal named, and the reason must hold at least one word of three letters or more; `-`, `n/a` and `ok` do not count. A marker without a reason waives nothing, and the refusal says so. A marker naming another rule, or sitting on another line, waives nothing. For a one-line docstring the marker can follow the closing quotes.

Use a waiver when the lint is wrong about this text, not to skip the rewrite. The gate prints how many waivers it honoured on every run.
