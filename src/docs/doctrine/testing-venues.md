# Doctrine — testing venues

> Venue routing, idleness, the two databases, and the process-identity gate.
>
> **What this file is.** These are the RECEIPTS behind rules that live in `CLAUDE.md`.
> Each entry was moved here verbatim on 2026-09-08 (sha `ed653c8b`, row `f1400995`) so the
> combined `CLAUDE.md` would fit under Claude Code's 150,000-char load limit. **Nothing was
> deleted.** The operative rule — the command, the table, the ⇒ ruling — stayed inline where a
> seat acts on it; what moved is the measurement narrative that explains why the rule is believed.
>
> **Read this when** you want to check a rule against its evidence, when you are about to change
> or retire one, or when you doubt a figure. **You do not need to read it to follow the rule.**


---

## Is another suite running — the 28-sample count instability

> Moved verbatim from `CLAUDE.md` 2026-09-08 (sha `ed653c8b`, row `f1400995`).
> The operative rule stayed inline; this is the receipt.

### 🔴 "IS ANOTHER SUITE RUNNING?" — MATCH `comm`, NEVER THE COMMAND LINE

Before taking the box for a tier, seats check whether anyone else is mid-run. **Measured 2026-08-29, both wrong answers on the same box within minutes:**

```bash
# ✅ CORRECT — asks what the process IS
ps -eo comm,args --no-headers | awk '$1=="pytest" || ($1 ~ /^python/ && $0 ~ / -m pytest/)' | wc -l
```

| pattern | reported | truth |
|---|---|---|
| `pgrep -f "\-m pytest"` | **0** | missed a live run — the script form `.venv/bin/python3 .venv/bin/pytest` has no `-m pytest` |
| `pgrep -af "pytest"` | **5** | four spurious |
| `comm`-based (above) | **1** | ✅ |

**The two failure modes are opposite, and the second is the dangerous one.**

1. **Too narrow → you take a box someone is using.** Matching only `-m pytest` misses `pytest` invoked as a script, which is how `run-*-tests.sh` launches it.
2. **Too broad → the gate never opens, on an idle box, silently.** `pgrep -f` searches the whole command line, and **a Claude seat's entire spawn briefing is its command line**. Three live seats — Tiberius, Rachel, Rio — matched `pytest` purely because their instructions *discussed* running tests. A briefing about testing is exactly the text most likely to contain the word, so this false positive gets **more** likely the more the fleet coordinates about the box.

⇒ `comm` answers *what this process is*; the command line answers *what someone wrote about it*. A gate must ask the first question. The same trap applies to any `pgrep -f` over a fleet of agent processes — grep for a tool name and you will find every seat that was told about the tool.


🔴 **AND THE COUNT IS NOT A WEAKER SIGNAL THAN THE IDENTITY — IT IS A DIFFERENT QUANTITY, AND AN
UNSTABLE ONE.** Tiffany 💍, 2026-09-05, on her own misreading. The command above is CORRECT and was
not the defect. **The defect was piping it to `wc -l` and reading the number** — which is the shape
almost every caller reaches for, because "is anything running" sounds like a counting question.

**Measured over ONE unchanging run, one tree, nothing else on the box:**

| samples at 20s | answered **ONE** | answered **TWO** |
|---|---|---|
| **28** | 24 | **4** |

⇒ Same run, same tree, same reality, and **the count returned 1 or 2 depending only on WHEN I
looked.** The coverage gate spawns transient pytest children; a sample landing on one sees two
processes. So the count does not measure occupancy at all — it measures *how many processes existed
at the sampling instant*.

🔴 **THAT IS A CORRECTNESS CLAIM, NOT A DILIGENCE ONE, AND THE DIFFERENCE IS WHY THIS SECTION EXISTS**
(Mr. Radio 🦉's framing): *"I should have looked more carefully"* is dismissed by every reviewer who
believes they would have remembered. *"The quantity moves under a still world"* cannot be fixed by
remembering, so it survives that reviewer. **`… | wc -l` then `-eq 0` cannot be made reliable by
being careful.**

⇒ **Ask the OWNERSHIP question instead, which is stable under identical sampling**: *is any pytest
here NOT mine?* A transient child of your own run is still yours, so it does not move the answer.

```bash
for p in $( ps -eo pid,comm --no-headers | awk '$2=="pytest" || $2 ~ /^python/ {print $1}' ); do
    case "$( tr '\0' ' ' < /proc/$p/cmdline 2>/dev/null )" in *pytest*)
        lr=$(  tr '\0' '\n' < /proc/$p/environ 2>/dev/null | sed -n 's/^LUPIN_ROOT=//p' )
        cwd=$( readlink /proc/$p/cwd 2>/dev/null )
        # environ OR cwd — and SAY which, because environ is not always readable
        ...  # emit MINE / PEER / UNKNOWN + tree, never a count
    esac
done
```

⚠️ **`/proc/<pid>/environ` IS NOT ALWAYS READABLE, and an env-only owner test then tags YOUR OWN
process as a peer.** Measured on this check's first live use — a transient child returned
*Permission denied*, the test found no `LUPIN_ROOT`, and fell through to PEER. ⇒ Decide on
**environ OR cwd**, print **which was used**, and emit **UNKNOWN** rather than PEER when neither
is readable: *"I could not tell"* and *"it is somebody else's"* are different facts, and only one
of them should stop a run.

⚠️ **The receipt for why this is worth a section**: the author reported *"still busy, 1 pytest"* to a
manager for four minutes about **her own coverage run**, in the same hour she told him to identify a
contender by tree rather than by pid, and while holding an observer whose log already named the tree.
**Knowing the rule is not the control. The instrument that cannot return a count is.**

🔴 **AND FIXING THE TAGGER WITHOUT FIXING THE GATE CHANGES NOTHING — THE INSTRUMENT TELLS THE TRUTH
AND THE DECISION READS A DIFFERENT QUANTITY** (Mr. Radio 🦉). A tagger emitting MINE / PEER /
UNKNOWN feeding a gate that still does `wc -l` then `-eq 0` is the original defect one level down:
the honest three-state answer is computed, printed, and **never consulted**. ⇒ **QUIET means zero
pytest AND zero UNKNOWN.** An UNKNOWN blocks exactly as a PEER does, because *"I could not tell whose
this is"* must never resolve to *"go ahead"*.

⚠️ **LIMIT, STATED RATHER THAN LEFT TO ASSUMPTION**: the both-unreadable path was exercised with
**synthetic input only; never observed live.** Its four siblings were observed on real processes. A
reader deciding whether to trust the UNKNOWN branch should know it is proven as logic and unproven
in the field.
