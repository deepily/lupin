---
capability: repo-tools-coupling-census
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.repo.coupling_census.ControlFailed@17d3b46686
  - cosa.repo.coupling_census.validate_needles@a5f9349a6c
  - cosa.repo.coupling_census.in_population@38f240a4d6
  - cosa.repo.coupling_census.is_code@0ad1455e18
  - cosa.repo.coupling_census.scan@032a6630f1
  - cosa.repo.coupling_census.check_controls@5ee3f7ae1f
  - cosa.repo.coupling_census.render@93af373950
  - cosa.repo.coupling_census.run@c6acbe0ef9
  - cosa.repo.coupling_census.main@48dce35c58
---
# Coupling census: counting Lupin-specific assumptions

`python -m cosa.repo.coupling_census` counts fixed-string needles over `git ls-files` of a tree and prints a markdown table stamped with the time and the commit sha. It backs section 4 of the code-health abstraction plan. The file lister and the git runner are the existing `doc_lint.cli.tracked_files` and `doc_lint.range_gate.git`.

## Rules
- `validate_needles` refuses a needle in three cases. Its kind is not an INI key, a pin or a registry key, its mapping is blank, or it is listed twice in a group. It raises `ValueError`.
- `in_population` leaves out a path with a directory named `.venv`, `node_modules` or `site-packages`, and the script's own file, which holds the needle list. `is_code` says whether a hit is production code, not a test, document, history file or `.backup-` copy.
- `scan` reads each file once as UTF-8 and matches every needle as a fixed string. It returns the hits sorted by path and line, with a count of files it could not read as text.
- `check_controls` requires that the first hit of each known coupling's needle is at its known line. A miss raises `ControlFailed`, and no count is printed.
- `render` builds the table: hits and files in code per needle, the first three locations, and what each maps to, then the population line.
- `run` ties these together for one tree and `main` is the command line. It returns 1 with a message when a control fails or git cannot list the tree.
