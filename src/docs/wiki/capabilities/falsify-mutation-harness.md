---
capability: falsify-mutation-harness
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - scripts.falsify.MutationRefused@8e82bf2e77
  - scripts.falsify.span_of@bb93ee793d
  - scripts.falsify.norm@8ed7d5e235
  - scripts.falsify.apply_mutation@28f574a84d
  - scripts.falsify.run_suite@84f6d83c88
  - scripts.falsify.falsify@a7b18fda50
  - scripts.falsify.main@a619fea841
---
# Falsify mutation harness

Proves where a falsifier bit, not merely that something went red. A mutation that lands somewhere other than where it was aimed still reddens the suite, and that red cannot be told apart from success. The harness makes every misplacement a hard refusal.

## Placing the mutation
- `span_of` locates a module-level function's line span by name, using the syntax tree, so the result is independent of indentation. A missing function raises `MutationRefused`, so a typo never mutates nothing, or something else.
- `norm` reduces a snippet to indentation-free lines for matching, so two snippets that differ only in leading whitespace compare equal.
- `apply_mutation` replaces the old block with the new block inside the named function only. The old block must appear exactly once there. Zero matches and two matches both raise `MutationRefused`.
- After writing, it re-parses the file and confirms the mutation sits inside the intended function. It re-indents the replacement to match the line it replaced and returns that line number.
- `MutationRefused` is an exception rather than a warning, because a warning would let a blind mutation run.

## Running
- `run_suite` runs one pytest file with random ordering disabled and returns the bare names of the failed cases and the summary line.
- `falsify` applies one mutation, runs the suite and reports which cases reddened. It always restores the original file, whether the run passes, fails or raises.
- Exit 0 means at least one case reddened. Exit 1 means nothing reddened, so the gate is blind to that change. Exit 2 means the mutation was refused.
- `main` reads the target, suite, function, old and new snippet files and an optional label.
