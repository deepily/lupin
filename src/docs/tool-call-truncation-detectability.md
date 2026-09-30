# Is a close-tag truncation detectable from the receiving side?

**Row** `cae4276c` · **Rio** · **2026-08-29** · guard: `src/tests/unit/test_every_tracked_python_file_parses.py`

A tool call whose payload contains a literal matching the harness's own parameter close-tag
terminates early, and the value lands **truncated** with no error raised anywhere. Two instances
happened in one day, both while writing files. This document answers the row's first question:
can the receiving side tell?

> ⚠️ **Do not write the triggering literal into a file.** Assembling it from pieces is the
> authoring-side practice, and — per the finding below — it is the *only* remedy available for
> prose payloads. Every sample in the guard is an ordinary unterminated string; none is a tag.

## Verdict first

**The answer splits, and the split is the finding: detectable exactly where the payload has a
grammar, undetectable exactly where it does not.**

| payload | detectable? | signal | measured |
|---|---|---|---|
| **Python** | **Yes, deterministically** | the file does not parse | **2,326 of 2,326 — 100%** |
| JSON / TS / YAML | Yes, same mechanism | the file does not parse | inherits the argument |
| **Prose** (markdown, commit messages, DM and store bodies) | **No** | none that separates it from a short value | best tail signal fires on **5.0%** of 15,455 genuine messages |

## Why Python is 100% and not merely likely

This is a mechanism, not a lucky sample. **The triggering literal can only ever be written
inside a string or a comment** — there is nowhere else in a Python file that text belongs. So
the cut always lands inside one, and the construct is always left unterminated.

Measured by cutting every tracked `.py` at a random point *inside a string token* — the position
where such a literal would actually sit:

```
files with a usable string token   2326
SyntaxError                        2326
parsed clean                          0
detection rate                    100.0%
```

For contrast, cutting at a *uniformly random* point catches only **78.1%** (307 of 393). The
realistic cut is the strictly easier case, which is the opposite of how these things usually go.

## Why prose is not detectable, with the number rather than the assertion

A truncated prose value ends in ordinary words. The obvious tail signal — *"ends without
terminal punctuation"* — was measured against genuine, complete messages written by the fleet:

| corpus | n | ends without terminal punctuation |
|---|---|---|
| DM submitted bodies | 15,455 | **778 — 5.0%** |
| git commit messages | 26 | **26 — 100%** |
| markdown ending on an opening delimiter | 1,629 | **103 — 6.3%** |

(104 distinct files are flagged by the union of the three markdown heuristics; the sets overlap.)

Against an event with **two known occurrences ever**, a signal that fires on 5% of a 15,000-row
corpus buries the specimen several hundred to one. On commit messages it fires on everything.
**These are false-positive rates, and they are what makes the prose half undetectable** — not an
absence of imagination about signals.

Two narrower signals were checked and also fail: trailing whitespace at end of value (0 of
15,455 real messages — but also not what a truncation leaves, since the cut is mid-sentence not
mid-space), and unbalanced quotes/backticks (0.7% of DM bodies, 11.5% of commit messages).

## How many past writes were silently truncated? Zero found.

| swept | n | truncations |
|---|---|---|
| tracked `.py` | 2,380 | **0** |
| tracked `.json` | 76 | **0** (one strict-parser false positive: `tsconfig.json` is JSONC, ends cleanly) |
| tracked `.md` | 1,629 | **0** — all **104** flagged tails adjudicated, not sampled: 30 end on a closing code fence, 73 on terminal punctuation or a table/list row, 1 on a complete sentence carrying a markdown hard break |

**What this does and does not establish.** For the structural half it is real evidence: a
truncation that survives would still not parse today, and none does. For the prose half **zero
found is worth almost nothing** — I have no signal that would have found one, which is the whole
point of the section above. The sweep covers the surviving tree, not history; a truncation that
was caught and fixed was never a silent loss, so the surviving tree is the population that
matters.

## ⚠️ It was NOT already covered, and the existing sweeps make it worse

The repo has several tree-wide AST censuses. They do not catch this, and one of them actively
hides it:

- `test_job_state_transition_call_sites.py:41` — `except ( SyntaxError, ValueError, OSError ):
  continue`. **A truncated file is skipped and the census silently shrinks.**
- `test_step12_internal_callers_use_flow_submit.py:142` — falls back to the raw text with the
  comment *"unparseable: fall back to the raw text, never quieter"*. **This one degrades safely**
  and is the right shape.

Measured, by truncating a real tracked file (`api_resource_manager.py`, 10,372 → 1,400 bytes):

| | result |
|---|---|
| the new guard | **RED, naming the file** |
| `test_job_state_transition_call_sites.py` | **7 passed — green** |

The per-edit `py_compile` mandate covers the file somebody remembered to check. The guard covers
the tree.

## The remedy, split to match the finding

- **Structured payloads → receiving side.** `test_every_tracked_python_file_parses.py`: every
  tracked `.py` must parse. Deterministic, ~2s, no configuration.
- **Prose payloads → authoring side, and there is no alternative.** Assemble any such literal
  from pieces at the point of writing. This is not a preference over a guard that was too
  expensive; it is the only thing available, and the 5.0% number above is why.

## Not established

- **JSON/TS/YAML have the same mechanism but were not separately measured.** The argument
  transfers — the literal can only sit inside a string — but I did not run the numbers, and the
  guard covers Python only.
- **The store and DM bodies were not swept for truncation**, because no signal exists to sweep
  them with. Naming it rather than implying the sweep was complete.
- **Whether the harness reports anything at the call layer** when the remainder text is orphaned.
  Establishing that means triggering the bug deliberately, which the row forbids.
