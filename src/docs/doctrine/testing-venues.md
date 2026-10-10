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

---

## The `:7999` suite list, moved out of CLAUDE.md on 2026-10-10

Row `cba9386c`. This is the list the root `CLAUDE.md` carried at `92a662e4d` under `### :7999 (dev) — AI-discretionary`, verbatim. A file on this list needs no monopoly; the three criteria that qualify a file are in `CLAUDE.md` § Testing venues.

Suites that qualify:
- `pytest src/tests/unit/`
- Inline `quick_smoke_test()` blocks + `py_compile` + import-chain checks
- `src/tests/smoke/test_calculator_live_pipeline.py`
- `src/tests/smoke/test_container_preflight.py`
- `src/tests/smoke/test_memory_cap_binds.py` — it runs `systemd-run` and gets a process SIGKILLed,
  which reads like a :8000 suite and is not one. The scope is transient (`--scope --collect`, dies
  with the command), so nothing persists; it takes about 0.5s; and the only process it kills is the
  allocator it started, inside a cgroup it owns. It needs no monopoly.
- `src/tests/smoke/test_credential_mount_shape.py` — it runs throwaway alpine containers on scratch files and
  reads the compute containers with `docker exec id -u`, so nothing persists and it needs no monopoly.
  `docker_smoke` runs it on the host with the two files below.
- `src/tests/smoke/test_db_roles_rollback_real_postgres.py` — it starts a Docker container, which
  reads like a :8000 suite and is not one. The container is a throwaway Postgres reached only by
  `docker exec`, with a name guard, memory and processor caps, and removal with its volumes at the end, so
  nothing persists and the real database is refused before any command runs. The file's five
  docker tests skip without docker (19 passed, 5 skipped with docker hidden); with docker the whole
  file, 24 tests, took 28.4s in one run (2026-10-08, at 9e9cfbce7). It needs no
  monopoly. Re-time it rather than trusting that figure.
- `src/tests/smoke/test_db_grants_real_postgres.py` — it reuses the rollback file's throwaway container,
  so the same reasoning holds: `docker exec` only, a name guard, removal at the end, nothing persists. Its
  17 docker tests all skip without docker and took 59.3s with it in one run (2026-10-08, at 9e9cfbce7). Re-time it rather than
  trusting that figure. It needs no monopoly.
- `src/tests/smoke/test_template_database_vector_real_postgres.py` and
  `src/tests/smoke/test_db_template_provisioning_real_postgres.py` — the template database
  `lupin_template_vector` (the vector extension, made once by `db_roles`, so the test role clones it with no
  superuser). Both reuse the rollback file's throwaway container, so the same reasoning holds. It is reached by
  `docker exec` only, behind a name guard, and removed at the end. Nothing persists and no monopoly is needed. With docker they took 11.1s (3 tests)
  and 28.0s (7 tests) in one run (2026-10-08, at 53ba759b9); with docker hidden every test skips (0.4s each).
  Re-time them rather than trusting those figures. They are not in `docker_smoke`'s list of three, so a
  skip there is not yet a failure.
- `src/tests/smoke/test_podcast_proxy_spent_cards_real_postgres.py` — the spent-card claim race on a real
  Postgres. It reuses the rollback file's throwaway container and its name and label guards, and connects
  with psycopg2 over the container's bridge address (no port is published). The address is refused when empty or
  when it is the real database's host, and the login password is random and never written to disk. The container
  is removed with its volumes at the end, so nothing persists and no monopoly is needed. With docker the four
  tests took about 8s in one run (2026-10-08, at b9d89658f); with docker hidden three skip and one passes (0.2s).
  Re-time it rather than trusting those figures. It is not in `docker_smoke`'s list, so a skip there is not yet a failure.
- `src/tests/websocket_smoke/` (run via `src/scripts/run-websocket-smoke-tests.sh`)
