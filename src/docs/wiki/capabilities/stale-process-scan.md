---
capability: stale-process-scan
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - scripts.stale-process-scan.running_processes@43db071a58
  - scripts.stale-process-scan.classify@7bf70c3d85
  - scripts.stale-process-scan.reachable_modules@9c4d39876f
  - scripts.stale-process-scan.changed_since@490236584a
  - scripts.stale-process-scan.scan@148116cbd3
  - scripts.stale-process-scan.main@d1844c0716
---
# Stale process scan

Finds long-lived processes running code older than a merge. Listeners pin their tree at boot, so a merge changes the file on disk while the running process keeps the module it imported. A saved file is not a served file, and a merged file is not a running file. The sibling [[delivery-collision-scan]] watches the earlier link.

## Two stages
- A process is reported stale only if both stages fire. Timing asks whether a commit touching its tree landed after it started. Reachability asks whether a changed module is imported, transitively, from its entry point.
- Timing alone over-reports. The first measurement flagged three MCP subprocesses and all three were false, because the changed file runs as a fresh subprocess and nothing imports it.

## Functions
- `running_processes` lists long-lived python processes running code from a lupin tree. It identifies them by the process `comm` name, never the command line, because a seat's whole spawn briefing is its argv.
- `classify` matches a process to a known long-lived class and its entry module, or returns `None` for anything transient. Two containers can run the same command, so the container is resolved from the cgroup and put in the label.
- `reachable_modules` walks the static import graph with `ast`, following only modules that resolve to files in this repo. It terminates on cycles and stops at a file limit.
- A function-level import counts as reachable, which over-reports. A false check costs a minute, and a false all-clear costs a day.
- `changed_since` returns, for the given paths, the newest commit after the process started.
- `scan` returns the stale processes and the stats. It raises `LookupError` when it finds zero classified processes, since an empty scan must refuse.
- `main` prints its denominators every run. Exit 0 means nothing stale, 1 means stale, and 2 means refused.
- It cannot see unmerged work, and it restarts nothing.
