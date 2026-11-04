---
capability: labelling-call-sites
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.repo.labelling.call_sites.calls_in@c012daa39f
  - cosa.repo.labelling.call_sites.find_call_sites@8fef586b8f
  - cosa.repo.labelling.call_sites.is_test_path@b31e43b4a5
  - cosa.repo.labelling.call_sites.tracked_python_files@0408fd4cb8
---
# Labelling: call sites

Shows where a key symbol is called, beside its source in a Set B item. The item format is in [[labelling-tools]]. Python only.

## What it does
- `find_call_sites` returns up to five `<path>:<line>  <source line>` strings for a symbol's short name.
- It leaves out the defining file and test files, which `is_test_path` recognises.
- `calls_in` finds the call lines in one source. A same-named function elsewhere can match, so the reviewer sees the line.
- `tracked_python_files` lists the tracked Python files of a tree.

## Don't
- Don't use it for a TypeScript key. The item then carries no call-site claim at all.
