---
capability: interchangeable-assertions-finder
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - scripts.find_interchangeable_assertions.literal_of@15ce20fd84
  - scripts.find_interchangeable_assertions.repeated_in@2667f8dfd0
  - scripts.find_interchangeable_assertions.findings_in_source@6b22b1ba24
  - scripts.find_interchangeable_assertions.scan@f3229736d6
  - scripts.find_interchangeable_assertions.render@0c42d5a015
  - scripts.find_interchangeable_assertions.main@a20f18042a
---
# Interchangeable assertions finder

A triage aid for one shape of blind fixture: an assertion whose expected values repeat, such as a pair of equal counts. Swapping the things those values describe cannot change the outcome, so the assertion measures their sum, not their identity.

## Finding
- `literal_of` returns the comparable literal an expression carries, or `None`. Only plain integer, string, float and boolean constants count.
- `repeated_in` handles a dict, tuple or list of at least two plain literals where one value repeats. It returns the value, how many times and the total. Anything else returns `None`.
- `findings_in_source` returns every such assertion in one file, at most one per assert statement, in source order. An unparseable file gives no findings.
- `scan` reads every path and returns the findings and the count of files read. An unreadable file is skipped and not counted, so it never reports as clean.

## Reading the result
- `render` prints a report with its caveat whether or not anything was found, and at most a limit of sites with the remainder counted.
- `main` returns 2 when no file could be read, 1 when findings exist and 0 otherwise. `--json` emits the findings, the files read and the caveat.
- A hit is not a defect, because a sibling assertion may tell the swap apart. A zero is not an all-clear, because most blind fixtures repeat no literal at all.
- Recall has no denominator. Quote results as a count against a named sample, never as a bare rate.
