---
capability: job-liveness-check
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - scripts.lib.job_liveness.read_cmdline@d8990c38e9
  - scripts.lib.job_liveness.read_ppid@fb06cc5ed5
  - scripts.lib.job_liveness.list_pids@f6cde5d9c2
  - scripts.lib.job_liveness.ancestor_pids@68101805f3
  - scripts.lib.job_liveness.find_matching_pids@8a80c950a1
  - scripts.lib.job_liveness.job_liveness@a19f9f7f84
  - scripts.lib.job_liveness.main@463b8a6444
---
# Job liveness check

A liveness check that cannot match itself. A run monitor once judged a paired eval alive with a process search. Its own command line held the pattern, so it matched itself and kept reporting running after the job died. Excluding its own process id was not enough, because the harness wraps commands in a shell that also holds the pattern.

## Process reading
- `read_cmdline` returns one process's command line as a space-joined string. It returns `None` when the process is gone, unreadable or a kernel thread. A process may exit between listing and reading, which is a normal race, so it never raises.
- `read_ppid` returns a parent process id from the stat file, or `None`. It reads the field after the last closing parenthesis, because the program name in the second field may hold spaces and parentheses.
- `list_pids` returns every process id present in the process directory, sorted, or an empty list when it cannot be listed.

## Matching
- `ancestor_pids` returns the caller's own id plus every ancestor up to init. Anything in this set is the watcher looking at itself. It stops at a depth limit and on a cycle.
- `find_matching_pids` returns the sorted ids whose command line matches a pattern, minus the watcher and its ancestors. An invalid pattern raises `re.error`, because a monitor watching a typo would report dead forever.

## Verdict
- `job_liveness` returns a state and the matching ids. The state is `RUNNING` when a non-watcher process matches and `DEAD` when the scan worked and nothing matched.
- It returns `UNKNOWN` when no readable process directory exists, so "could not look" is never read as "not there". An empty pattern raises `ValueError`, since it would match everything.
- `main` prints the state and any matching ids, and exits 0, 1 or 2 for running, dead or unknown. A bad pattern is reported as a usage error.
