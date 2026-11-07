---
capability: duplicate-check-daily-window
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_mcp.duplicate_check_daily.git@d3ea117dc1
  - lupin_mcp.duplicate_check_daily.read_last_success@0ce5369a97
  - lupin_mcp.duplicate_check_daily.window_of@b87fc88823
  - lupin_mcp.duplicate_check_daily.changes@69474b63bc
  - lupin_mcp.duplicate_check_daily.changed_files@af39eb4bf8
  - lupin_mcp.duplicate_check_daily.old_paths@44460499c8
  - lupin_mcp.duplicate_check_daily.new_definitions@5f7efaf3d2
  - lupin_mcp.duplicate_check_daily.release@78925fda8f
  - lupin_mcp.duplicate_check_daily.pool_without_earlier_versions@157e09aba7
  - lupin_mcp.duplicate_check_daily.progress@29d6340dbb
  - lupin_mcp.duplicate_check_daily.write_json@d65f1e03d9
  - lupin_mcp.duplicate_check_daily.baseline_window@bd338e256d
  - lupin_mcp.duplicate_check_daily.baseline_definitions@808875bb59
  - lupin_mcp.duplicate_check_daily.read_baseline@c51274d43b
---
# Duplicate check daily: window and new definitions
The first half of `lupin_mcp.duplicate_check_daily`: which commits a run judges, which definitions are new, and how far it got. The run itself is in [[duplicate-check-daily-run]].

## What it does
- `git( root, *args )` returns the stripped stdout. It raises `RuntimeError` naming the command when git fails.
- `read_last_success( folder )` returns the parsed `last-success.json`, or None when there is none.
- `window_of( root, last, now, branch, hours )` ends at the tip of `main`. It starts at the last good commit, else at the newest commit older than 24 hours, else at the first commit.
- Its `commits` are those after the start up to the end on the first-parent line, oldest first.
- `changes( root, window )` returns `( old path, new path )` for each added, modified or renamed file. Old is None for an added file. A deleted file is not listed.
- `changed_files` is the sorted new paths of Python and script files. `old_paths` maps each renamed file to the path it had at the start.
- `new_definitions( tree, root, window )` returns `{ defs, commit_of }`, ordered by the commit that last touched the file, then file and line.
- A definition is left out when the window's start held the same file, name and text. A renamed file is compared with its old path, so a rename alone judges nothing.
- `baseline_window( root, branch )` is the whole branch, from its first commit. `baseline_definitions( tree, window )` lists every definition of the tree's Python and script files, in file and line order, each tied to the window's end.
- `read_baseline( folder )` returns the parsed `baseline.json`, or None. Its status is `in_progress` or `complete`.
- `release( root, tree )` unlocks and removes a detached worktree. It raises nothing.
- `pool_without_earlier_versions` drops, from the tree's server and client definitions, any that share a file and name with a new one. No new definition pairs with its own earlier version.
- `progress( defs, commit_of, unjudged, window )` returns `{ advanced_to, carried }`. A definition the cap or a failed call left unjudged is carried. An unreadable reply was ledgered and is not carried.
- `advanced_to` is the commit before the first one with a carried definition, or the window's start when that is the first. With nothing carried it is the window's end.
- `write_json( path, doc )` writes the document, makes the folder and returns the path.
