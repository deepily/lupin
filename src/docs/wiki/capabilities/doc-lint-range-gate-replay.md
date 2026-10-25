---
capability: doc-lint-range-gate-replay
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.repo.doc_lint.range_gate.RangeRefused@852082ed4b
  - cosa.repo.doc_lint.range_gate.git@449d7bec08
  - cosa.repo.doc_lint.range_gate.git_bytes@698ce63054
  - cosa.repo.doc_lint.range_gate.list_commits@50b68ecd59
  - cosa.repo.doc_lint.range_gate.changes@17eb0424f7
  - cosa.repo.doc_lint.range_gate.stage@2786561772
  - cosa.repo.doc_lint.range_gate.run_gate@072935728f
  - cosa.repo.doc_lint.range_gate.parent_gate@09ced90ca1
  - cosa.repo.doc_lint.range_gate.check_commit@193f5919b6
  - cosa.repo.doc_lint.range_gate.check_range@f1d8a5afed
  - cosa.repo.doc_lint.range_gate.exit_code@f68f74c107
  - cosa.repo.doc_lint.range_gate.epoch_line@bee05c6db8
  - cosa.repo.doc_lint.range_gate.report@117629efb6
  - cosa.repo.doc_lint.range_gate.now@cf4ab12ed6
  - cosa.repo.doc_lint.range_gate.where@0b0132220e
  - cosa.repo.doc_lint.range_gate.holder_pid@19cf8bc4c4
  - cosa.repo.doc_lint.range_gate.sweep_stale@f6093df024
  - cosa.repo.doc_lint.range_gate.main@c667f9a351
---
# Doc-lint range gate replay

Replays the commit gate over every commit of a range, so a push can be judged commit by commit. The epoch rules are in [[doc-lint-range-gate-epoch]]; the gate itself is [[doc-lint-gate]].

## Replaying a commit
- `list_commits` lists `base..head` oldest first. `changes` lists what one commit changed against its first parent as status, path and old path. `stage` applies those changes to a worktree holding the parent.
- `run_gate` runs the gate of a worktree, with `--blocking` for a held commit. `parent_gate` builds a runner that uses the gate code of the commit's parent. A commit that edits `gate.py` is judged by the old one.
- `check_commit` returns a `Result` of `passed`, `refused` or `unchecked`. Exit 0 is passed and exit 3 is refused. Any other exit, or a git failure, is unchecked.
- `check_range` judges every commit oldest first and does not stop at one it cannot judge. A range whose base descends from the epoch holds every commit to blocking.

## Reporting
- `exit_code` returns 2 when any commit was unchecked, else 1 when any was refused, else 0. `epoch_line` and `report` give one line per commit with its verdict and the epoch used.
- `now` and `where` stamp an unchecked line with the worktree and the time. `RangeRefused` carries a refusal to exit 2. `git` and `git_bytes` return a command's text or bytes.

## Running it
- `main` makes a detached worktree under `.claude/worktrees`, removes it on every path, and takes `--base`, `--head` and `--out`. An empty range or a bad epoch exits 2.
- The holder folder is named `range-gate-PID-suffix`. `holder_pid` reads the pid, and `sweep_stale` removes holders whose pid is dead or missing, and never touches a folder with another name.
