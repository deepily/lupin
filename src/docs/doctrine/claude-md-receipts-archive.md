# Archive — the receipts pulled out of CLAUDE.md

> Rick's ruling, 2026-09-08: *"I don't give a shit about the receipt and the reconciliation. That's
> history. I just want the simply stated rule. Nothing has to be proven — if it's in there it's because
> it belongs there, not because it needs to be proven at every rereading."*
>
> So `CLAUDE.md` now carries **rules only**. Everything below is the measurement narrative that used to
> sit under each one: who measured it, when, the reconciliation tables, the corrections and retractions.
> It is kept for anyone tracing where a rule came from, and it is **not required reading**.
>
> Pulled 2026-09-08 from sha `ed653c8b` by Mr. Radio 🦉, row `f1400995`. Nothing was deleted; git holds
> every prior revision as well.


---

## 🔴 THE COMMIT SCOPE GUARD REVIEWS THE `git commit` LINE — A HEREDOC *ON* THAT LINE MAKES IT GIVE UP


The guard reads which paths a commit names and checks them against your section of
`.claude-session.md`. It refuses to guess: hand it a command it cannot parse and it
**allows the commit** with `⚠️ Commit scope guard: NOT REVIEWED — <why>`. That notice
is easy to walk past, and the commit lands unexamined.

**Measured 2026-09-01** against the guard's own `git_commit_match` + `_pathspec_of`,
one variable at a time. The `reviewed` rows are the positive control — without them a
`BYPASSED` would only prove the probe always says bypass:

| command shape | |
|---|---|
| `cat > msg.txt <<'EOF' … EOF ; git commit -F msg.txt -- <paths>` | ✅ **reviewed** — this is the mandated pattern |
| … the same, `&&` joined | ✅ reviewed |
| … the same, plus `2>&1 \| tail -3` | ✅ reviewed |
| … whose heredoc **body** contains the words `git commit -F x -- evil.py` | ✅ reviewed |
| `git commit -F msg.txt -- <paths>` | ✅ reviewed |
| `git commit -F /dev/stdin -- <paths>` (no heredoc) | ✅ reviewed |
| `git commit -F <(printf m) -- <paths>` | ✅ reviewed |
| `printf m \| git commit -F - -- <paths>` | ✅ reviewed |
| `git commit -F /dev/stdin -- <paths> <<'EOF' … EOF` | 🔴 **BYPASSED** |
| `git commit -F msg.txt -- <paths> <<'EOF' … EOF` | 🔴 **BYPASSED** |
| `git commit -F - -- <paths> <<'EOF' … EOF` | 🔴 **BYPASSED** |
| `git commit -F /dev/stdin -- <paths> <<< 'body'` | 🔴 **BYPASSED** |

⇒ **The rule is about ATTACHMENT, not about heredocs.** A heredoc in a *preceding*
command is fine — write the message file with one and commit cleanly, exactly as the
session-end workflow already prescribes. What goes unreviewed is feeding the message
**to the commit itself** through a heredoc or here-string on that line.

**The mechanism says why, and it predicts the table without running it.**
`_pathspec_of` reads only `command[ match.end(): ]` — the tail *after* the `git commit`
match — then splits at the first `;`, `&`, `|` or newline. A preceding heredoc is not
in that tail and can never reach the check. What *is* in the tail meets
`_strip_heredoc_bodies`, which removes the heredoc **body** and leaves the operator; the
surviving `<<` then trips `_without_redirections`, which returns "not sure" rather than
risk misreading the paths.

⚠️ **This is a deliberate refusal, not a parsing bug**, and the same design this page
asks for everywhere: a step that cannot finish declines and says what it did not do.
The gap is only that its output *looks* like success. If you see NOT REVIEWED, either
re-run in the reviewed shape or check the commit yourself with `git show --stat <sha>`
— and say which you did.

**Pinned by a test, so a change to any of this is visible rather than silent**:
`src/tests/unit/test_commit_scope_guard_heredoc_attachment.py` — both directions, plus
a controlled pair whose only variable is where the heredoc sits. It pins TODAY'S
behaviour and does not assert the give-up is correct; whether it should fire when the
pathspec already parses cleanly is an open ruling.

⚠️ **Do not restate this as "no heredocs near a commit."** That phrasing was written
and withdrawn the same evening: read literally it bans the mandated pattern, and a
reader following it would abandon a workflow that works. **An ambiguous rule fails the
way an ambiguous pointer fails** — say *attached to the `git commit` invocation*, which
has one reading.

---

### Spawn-brief line (the short form, for a brief that cannot carry the table)

- **Commit with `git commit -F <file> -- <paths>`.** Write the message file first (a
  heredoc there is fine). **Never attach a heredoc or here-string to the `git commit`
  line itself** — `-F /dev/stdin <<EOF`, `-F - <<EOF`, `<<< 'body'` — the scope guard
  cannot parse those, prints `NOT REVIEWED`, and lets the commit through unexamined.

---


---

## 🔴 A CLEAN EXIT IS NOT EVIDENCE THE WORK HAPPENED


**Five instances in one evening, 2026-08-30, in five different tools.** Written as one rule because
five seats each found it separately and none of them recognised it as the same shape until they were
put side by side.

| tool | the clean-looking result | what it actually meant |
|---|---|---|
| `--cov=<bad target>` | exit 0, no coverage table | **nothing was ever measured** |
| `migrate-pyc…--verify` on a fresh tree | exit 0, ✓ | **nothing there to judge** — vacuous, not converted |
| `purge-pycache.sh --verify` | exit 0 | **flag ignored**, and it purged |
| `purge-pycache.sh` on an emptied tree | exit 0, *"nothing to purge"* | **it never ran** — the previous command had emptied it |
| `rc == 1` as a mutation kill | looks like a kill | the suite was **already red** at baseline |

⇒ **THE FAILURE AND THE SUCCESS PRINT THE SAME THING.** In every case the caller checked the exit
code, saw what they expected, and carried a conclusion forward that the tool had never supported.

🔴 **THE FIX IS A TOOL THAT REFUSES, NOT A CALLER WHO CHECKS** (Rachel 🕊️, correcting the first cut
of this rule, which asked the reader to be vigilant — and a rule that depends on remembering is not a
control, which is this page's own doctrine).

**A tool facing a job it cannot finish has two options, and only one of them is honest:**

| ❌ no-op and report cleanly | ✅ REFUSE and say what it did not do |
|---|---|
| purge, then fail to reconvert, exit 2 with the caches gone | `Refusing to purge: the reconvert would fail. 1 __pycache__ directories left untouched.` |
| apply a mutation at a guessed location | `ANCHOR MATCHED 2x — NOT APPLIED` |
| report coverage for a target never imported | name the target and say it was never imported |

**Both live examples are from tonight and both are ours**: Rio's purge script declines *before* the
`rm` when the reconvert cannot run, and Rachel's mutation harness skips an arm whose anchor matched
twice rather than guessing at placement. **Neither leaves the caller a clean-looking result to
misread**, which is what makes them different in kind from a checking rule.

⇒ **Build this into anything you write.** A step that cannot complete must decline the whole
operation and name the part it did not do — never half-finish and return a status the caller can read
as success.

**Until a tool refuses, the caller's fallback is the tool's own account of what it touched — never
the exit code:**

| ask | not |
|---|---|
| does the coverage table list the file? | did it exit 0? |
| does the verify name **your** tree in *scanned roots*? | did it print ✓? |
| does the purge report a **count** matching what you planted? | did it say nothing to purge? |
| did a **named test that was passing** now fail? | is `rc` non-zero? |

⚠️ **THE SECOND-RUN TRAP, and it is the one that nearly published a wrong result** (Rachel 🕊️): she
ran arm B of a two-arm comparison *after* arm A had already emptied the tree. It printed **"nothing
to purge"** and **exited 0**, and the check afterwards then failed — reading exactly like *arm B does
not work* when arm B **had not run at all**. She caught it because the phrase did not match a tree she
had just populated by hand.

⇒ **In a two-arm comparison, each arm needs its own freshly built state**, and **read the tool's
narration, not just its status.** An arm that no-ops because the previous arm consumed its input is
indistinguishable from an arm that failed — and it is the second arm, the one you are testing, that
gets the blame.


---

## 🔴 CHECK YOUR OWN SUBPROCESS'S AGE BEFORE YOU FILE A DEFECT — A STALE STDIO SUBPROCESS MAKES AN ALREADY-FIXED DEFECT REPRODUCIBLE ON DEMAND


Tiberius 👑, 2026-09-04. **Normally, reproducing a defect on demand is the strongest evidence that it
is live. Here it is the opposite — and the more reliably it reproduces, the more convincing the wrong
conclusion looks.**

A stdio MCP server — cosa-voice is registered stdio — is a **subprocess started once, when your seat
started.** A fix that lands on disk afterwards does not reach it. So a seat whose subprocess predates
the fix reproduces the old behaviour perfectly, on demand, forever, and reads that as *the defect is
still live*.

**The receipt, and it needed two independent halves rather than one**: rows `7975c302` and `9b920649`,
resolved by a transcript showing three `dismiss_sessions` calls at **12:33 / 13:02 / 13:16 EDT**, set
against a process-continuity read showing the same subprocess alive from **11:09 to 22:47 with no
restart**. Either half alone is compatible with a live defect; together they are not.

⇒ **Before filing, ask how old the process you are testing THROUGH is.** For a stdio server that is
your own session's subprocess age — not the box's uptime, and not the mtime of the file you fixed.

⚠️ **AND NO PEER CAN CATCH THIS FOR YOU.** The staleness is **per-subprocess**, so it is invisible
from outside the seat: someone running the same call through their own fresh subprocess sees the fix
and cannot reproduce your finding — which reads as a **disagreement about the code** rather than a
difference in instrument age.

⚠️ **This is the familiar staleness note pointed the OTHER WAY, and that direction is dearer.** The
usual one lives in the **GLOBAL `~/.claude/CLAUDE.md`** (§ MANAGER SPAWN/HARVEST AUTONOMY, the
`:7999` bounce row) — *auto-reload is OFF, so a saved file is not a served file* — and it is about
the **notification server**, not about an MCP stdio subprocess, which is why this section stands on
its own rather than pointing at it. That one costs you **a fix you think you have**, and it surfaces
the moment you look. This one costs you **an evening chasing a corpse**, and every hour of it
feels like progress, because the defect keeps reproducing on cue.


---

## 🔴 The overclaim hides in the JOIN, and grep cannot find it


Two true, separately-measured statements get welded with a *because*, a *so*, or a *which means* — and
the weld is a third claim nobody measured. It survives review, including your own, because **a join is a
relationship between two sentences and contains no string to search for.**

⇒ **Read your conjunctions one at a time.** For every *because* / *so* / *which means* / *therefore*, ask:
**did I measure the LINK, or only the two ends?** If only the ends, state them as two facts and stop — the
reader can draw the arrow, and if the arrow is wrong your facts still stand.

🔴 **Name the gap and you have created the string.** An inferred bridge reads stronger than either end and
cannot be audited; a named gap — *"A. B. I did not measure the link."* — reads weaker, is searchable, and
recruits whoever holds the other half.

🔴 **One kind of link is not merely unmeasured but unmeasurable: a mental state.** An artifact can show
you what was produced and never why. **The two want opposite responses** — an UNMEASURED join says *go
and measure the link*; an UNMEASURABLE one says **do not make the claim at all.** Reading the second as
the first sends someone after evidence that cannot exist, which looks like diligence.

⚠️ **Naming a person raises the bar.** Strip an inference about a colleague to what you measured — *his
pycs were timestamp-based* is a fact about a tree and carries the same rule.

⚠️ **It bites hardest where it lasts longest.** A DM is retracted in a minute; a commit subject, a
docstring and a test header are read for years by people who never see the retraction. **A retraction
must reach the artifact, not just the conversation.**

[receipts — the three independent 2026-08-30 firings, the self-caught mental-state instance, the
comparison-of-incomparable-populations tally → doctrine/claim-construction.md]

### 🔴 A reap reports `prior_holder_present` and proceeds — so "write a memento" and "a memento is on disk" are different facts

The verdict field is the hazard: `prior_holder_present` is a **note, not a refusal**, and a stale file in
the slot looks exactly like a fresh one to everything except its timestamp and its session id.

🔴 **The rule is a WAIT, not a check**: ask for the memento, then **wait for the worker to say it is on
disk** — with the record path and its session id — before calling `dismiss_sessions`. A worker's ack is
the only signal distinguishing *their* file from *somebody else's file in their slot*.

⇒ **A failure that explains itself in a field you were not reading teaches you nothing at all.** Naming
the problem in the output is not the same as delivering it; a field nobody reads is closer to silence
than to a warning.

### 🔴 Retiring a gate does not retire the thing it gated

**A row id in a status line is read as current unless marked otherwise.** Cite a closed row as
`69f3b917 (dropped)`, or the reader inherits a constraint that no longer exists.

⇒ **A gate's removal changes WHO MAY ACT, never WHETHER THE THING EXISTS.** Collapsing the two turns a
decision somebody made into a no-op that made itself, and erases the only part worth reviewing — why
they held.

### 🔴 A spawn brief is the one document a seat cannot notice being wrong

It arrives before there is any tree, any sensor or any peer to check it against — so the obligation is
the **brief-writer's**, not the reader's:

| write | not |
|---|---|
| *"`self_respin` failed on MY seat at 09:40; not tested elsewhere"* | *"`self_respin` is down"* |
| **the population a claim was measured on** | the claim alone |
| **INHERITED — re-derive before acting** | an inherited claim restated as your own finding |

⇒ **An inherited claim you restate as your own becomes yours at the moment you could have checked it.**

[receipts → doctrine/claim-construction.md]


---

## 🔴 ATTRIBUTION AND A SCOPE CAVEAT DO NOT MAKE A LEAD SAFE ON A DURABLE SURFACE


Tiberius 👑, 2026-09-04, correcting a reviewer who believed the hedge had discharged the obligation.
**A caveat protects the reader of the CONVERSATION. Only OMISSION protects the reader of the
ARTIFACT.**

**The receipt.** I put a hedged hypothesis on his row — attributed, and explicitly marked as not
established. María 🌸 then refuted the hypothesis outright. **The hedge did not survive the trip:**
*"not established"* is exactly the clause a skimmer drops — **the same way a condenser drops a
negation first** — and what stays on the durable row is the hypothesis, wearing my name.

⇒ **On anything durable — a row body, a commit subject, a docstring, a doc — an unmeasured lead is
not made safe by labelling it. Leave it out, or go and measure it.**

🔴 **AND ITS BOUND, ALSO HIS, BECAUSE WITHOUT IT THE RULE OVER-APPLIES: THIS IS ABOUT SPECULATION,
NOT ABOUT UNCERTAINTY.** A measured don't-know **stays** — *"20 unparseable"*, *"23 undecidable"*,
*"mechanism open"*, *"n=3, one host"* are findings, and deleting them would strip this file of exactly
the honesty it spends most of its length demanding.

| the test — one question, asked of yourself | keep it? |
|---|---|
| I **measured** this, and the answer came back uncertain | ✅ **say so** — the uncertainty IS the finding |
| I **asserted** it without measuring, then softened it | 🔴 **omit it** — the softening is decoration |

⚠️ **The two look IDENTICAL on the page.** *"Possibly X"* is a measured don't-know or a dressed-up
guess depending entirely on what you did before you typed it, and nobody downstream can tell which.
**You are the only person who can apply this test**, which is why it is a writing rule and not a
review rule.


---

## 🔴 A COORDINATE IS NOT A REFERENCE — NAME THE CONTENT


**Derived independently three times on 2026-08-30** — Tiberius 👑 and Maya 🌻 from different
directions, and a third time when this reviewer handed a peer `CLAUDE.md:888` as an insertion point
for a file that had already moved several times that day, by the very commit under review. Written
here because a lesson three seats reach separately is one the file should have carried already.

**A coordinate says WHERE something sat when you looked. A reference says WHAT it is.** Only the
second survives someone else editing between your reading and their acting — and in a fleet, someone
always does.

| Don't hand over | Hand over |
|---|---|
| `CLAUDE.md:888` | the anchor sentence, verified to match **exactly once** |
| `stash@{2}` | the commit sha (`git rev-parse` it first) |
| "the third finding in the output" | the finding's own text or id |
| "the file I edited earlier" | the path, and the sha or content hash you read |
| "as of tonight" | the sha, or the wall-clock time of the read |
| a **PID** you captured earlier (`kill $PID`, a watcher armed on it) | the process's own identity — `readlink /proc/<pid>/cwd`, the command via `comm`, or a pidfile the process itself writes |

⚠️ **A PID IS THE SHARPEST MEMBER OF THIS FAMILY BECAUSE THE OS RECYCLES IT FOR YOU** (sam 🎙️,
2026-09-02). He armed a watcher on a PID; the process it named had already died, and the watcher
reported **"finished"** — a confident answer about a process that was gone, and **silence about the
run he actually cared about, which was still writing.** Reading that as a finished run, he launched
another, and **two full unit tiers then ran in the same worktree at once**, both writing into one
tree, for minutes, invisibly.

⇒ **He found it by keying on the thing rather than the number** — `readlink /proc/<pid>/cwd` across
every process, which named his tree twice. **Identify by a property the thing carries, not by a
handle you captured when it was true.**

**The tell is mutability, not format.** A line number in a frozen artifact is fine; a line number in
a live file is a bet that nobody edits above it. `stash@{N}` renumbers when any entry is dropped —
that hazard is already in the global CLAUDE.md, and this is the same defect wearing a different
notation, which is exactly why it keeps being re-derived instead of recognised.

⚠️ **AND A COORDINATE MUST SAY WHICH SPACE IT INDEXES INTO — "HASH" NAMES THREE DIFFERENT THINGS ON
THIS FLEET** (Tiberius 👑, 2026-09-04, correcting a reviewer who ran all three together in one
paragraph as though they were interchangeable). They are the same SHAPE and they resolve with
different commands:

| kind | example | how the reader resolves it |
|---|---|---|
| **task-store row id** (uuid prefix) | `7975c302` · `9b920649` | `task_get` |
| **memento CONTENT sha256** prefix | `40424d50` | hashes the file's bytes — it is not a git object at all |
| **git commit** | `b6bcf1ce` · `07290597` | `git show` |

⇒ **Calling all three "hashes" makes every one of them unresolvable.** A hex string with no named
space is a coordinate that does not say which map it belongs to, so the reader's first command fails
and they cannot tell a wrong id from a wrong tool. **Say the kind with the id** — *row `7975c302`*,
*commit `07290597`* — which costs one word and is the difference between a pointer and a puzzle.

**When you must point at a position, make the pointer self-checking**: give the anchor text, say it
must match **exactly once**, and say what to do when it matches zero or twice — *come back to me*,
never *guess at placement*. A pointer that cannot fail is a pointer that silently lands in the wrong
place.

**AND THE SAME RULE GOVERNS THE CHANNEL, NOT ONLY THE POINTER** (Maya 🌻 §1.5.1b — *adapt what you
send to the channel you measured*). Text sent between sessions is **condensed in transit**, and a
condenser reorders and drops. Measured 2026-08-30: an insert handed to a peer for verbatim paste
arrived **summarised**, and he correctly rebuilt it from its three points rather than pasting what
he received — the hand-off worked only because he flagged it. ⇒ **Send a to-be-pasted artifact
BARE — one artifact per message, no surrounding prose for the condenser to fold it into** — and say
plainly that it is verbatim. A paragraph explaining the paste is the thing most likely to absorb it.

⚠️ **THIS DOES NOT CONTRADICT "STATE THE COORDINATES", AND THE TWO ARE EASY TO READ AS OPPOSITES.**
They govern different acts. **Reporting a measurement**: state the coordinates — the sha, the frame,
the root set, the wall-clock time — because without them a reading is not wrong, it is
*unfalsifiable*. **Pointing someone at content**: name the content, because a coordinate is what
goes stale. ⇒ *Coordinates make your reading checkable. Content-names make your pointer durable.*
Say what you measured **and** name what you mean.


---

## 🔴 A TEST THAT ENTERS BELOW THE LAYER THE INCIDENT ENTERED AT CANNOT SPEAK TO THE INCIDENT


Rachel 🕊️, 2026-09-02, on her own shipped commit. **A check can be correct, pass, and prove nothing
about the failure it was written for — because it knocked on a different door than the incident
did.**

**THE RECEIPT.** A fix made a spawn into the shared main checkout announce itself, at WARNING and on
the spawn payload. It shipped with an "end-to-end" receipt that called `provision_worktree_venv`
directly, **with the main repo's path handed to it**. That proves the helper announces a main-repo
target. It says **nothing** about whether the real spawn path ever REACHES that branch — and the
incident was a spawn, not a helper call. I reported the first as if it settled the second.

⇒ **THIS IS NOT ABOUT MOCKING.** Nothing was mocked in either version: the helper, the script and
the refusal were all real. It is about **where you knock.** A real component exercised at the wrong
altitude is still the wrong measurement, and it does not look like one — it looks like a green
end-to-end test, which is the most reassuring thing a report can contain.

**HOW IT WAS CLOSED, and both halves were required.** Drive the layer the incident used — the real
`spawn_sessions`, real `_resolve_project_root`, real `provision_worktree_venv`, real
`link-worktree-venv.sh`, only the tmux launch stood down by `dry_run` — with ONE variable between
two cases:

| `LUPIN_ROOT` | status | `placement_alarm` | WARNING |
|---|---|---|---|
| the main checkout | `main_repo` | names the tree | yes |
| an ordinary worktree | not `main_repo` | `None` | none |

**The second row is not optional.** *"The alarm fires"* and *"the alarm fires WHEN IT SHOULD"* are
different claims, and an alarm that shouted on every spawn would satisfy the first. Guard:
`src/tests/unit/test_the_real_spawn_path_announces_the_placement.py`, whose three arms are the proof
it discriminates rather than merely passes.

⇒ **THE DISCHARGE IS ONE QUESTION, ASKED BEFORE THE TEST IS WRITTEN: at what layer did the incident
ENTER?** Then enter there. Not *"does my check work"* — it does, that is the trap. **A helper-level
receipt and a path-level receipt are different claims, and only one of them is about the incident.**

⚠️ **AND IT BITES HARDEST AFTER THE FIX IS ALREADY WRITTEN**, because by then the component is
known-good and testing it feels like confirming the work. It confirms the component. The path is
what broke.

⚠️ **RELATED, SEPARATELY OWNED, AND DELIBERATELY NOT FOLDED IN HERE.** Two other checks disagreed
with their subjects the same evening — Sam 🎙️'s route guard matching on a **shorter key** than the
router's (path where Starlette uses path AND method), and María 🌸's `dist/` count from a **shallower
scope** than the tree (§ *THE WORKTREE ARTIFACTS THE TIER CANNOT SEE*). They rhyme with this and they
are not this. **Sharing an evening is not sharing a finding** — Mr. Radio 🦉's ruling, and Sam
declined the pairing himself before it was put to him: *"a forced pair is worse than one clean
example."* Each is filed under the person who measured it, in their own words. **A rule assembled
from someone else's half-remembered receipt is this section's own defect wearing a byline.**


---

## 🔴 IMPLEMENTED BUT NOT INSTALLED — A MODULE AT 100% THAT THE APP NEVER MOUNTS


Rachel 🕊️, 2026-09-02, and she proved it with the arm rather than asserting it. **A component can be
complete, correct, fully covered and entirely absent from the running system, and every test that
builds the component itself stays green.** Coverage cannot see it; the class of test that can is the
one people skip as ceremony.

**The case.** `/static/` was served with no `cache-control` at all — 9 of 9 versioned assets, token
or no token, measured against the live mount. The fix is a `VersionedStaticFiles` class plus **one
line** at `src/lupin_app/main.py:1375`, which is the app's ONLY static mount (verified: two hits in
the file, the import and the mount).

⇒ **Every test that instantiates `VersionedStaticFiles` itself passes whether or not `main.py` ever
mounts it.** So a revert of that single line leaves the module at 100%, its own suite green, and the
server handing out exactly the headers the bug was about.

**The mutation arms, and note which one carries the finding** — baseline 0 failing, restore control 7
passed:

| arm | what it breaks | new reds |
|---|---|---|
| **C1** | **revert the mount to plain `StaticFiles`** | **2 — and NOTHING ELSE catches it** |
| C2 | one policy for every URL | 3 |
| C3 | cache the un-tokened URL hard | 3 |
| C4 | `max-age` too short | 1 |
| C5 | token detection inverted | 3 |

⇒ **C1 is the whole argument.** The two tests that catch it `import lupin_app.main` and interrogate
**the app object it assembles** — the route table, not the source text. Without them the revert is
invisible to a suite that is otherwise thorough.

🔴 **SO ASK, OF ANY NEW COMPONENT: does a test drive the ASSEMBLED APP, or only the class?** A suite
made entirely of the second kind reports on a component; it says nothing about the product. **This is
§ *A HIT IS NOT A USE* moved from search to wiring** — there, a name appears without the code using
it; here, code exists without the app reaching it.

⚠️ **AND TWO PRACTICES FROM THE SAME PASS, both worth copying.**
- **The corpus guard discovers its nine assets FROM THE PAGE and carries a positive control asserting
  it found at least five** — because *an empty discovery passes every per-item assertion in the loop*.
  A loop over nothing is green. (Same defect as § *AN EMPTY RESULT IS TWO DIFFERENT FAILURES*.)
- **She named C4 as her thinnest arm rather than padding the count** — a short `max-age` is a
  degradation, not a broken policy. **A 5-of-5 that quietly includes a weak arm is how a kill count
  stops meaning anything.**

⚠️ **Two policies, not one, and the reason generalises past headers**: a tokened URL names ONE
revision so it can never need to change (`immutable`), while an un-tokened URL must serve tomorrow's
bytes (`no-cache`). **Applying either rule everywhere re-creates the other's bug** — and caching the
un-tokened path hard is the same stale-asset trap one level down, which is the defect that produced
this work.


---

## 🔴 A TWO-FILE INVOCATION CANNOT TELL YOU WHICH FILE THE RESULT CAME FROM


Rio ⚡'s line, 2026-09-02, found on his own run after two other seats had spent a measurement each
chasing it. **pytest's summary reports a UNION and every reader hears one file.**

**The receipt.** Three seats ran the same cache-bust guard at one sha and got two different answers
— **4 passed / 5 skipped** twice, **4 passed / 6 skipped** once. The guard **discovers its own
corpus** from the page rather than carrying a list, so a corpus that changes size at a fixed sha
looks exactly like a discovery reading something other than the sha. That is a real and alarming
shape, and it is what everyone went to investigate.

⇒ **There was no sixth asset.** He had passed **both** guard files to pytest in one invocation. The
extra skip came from the OTHER file, and `40 deselected` was on screen the whole time saying so.

| what the summary line says | what it means |
|---|---|
| `4 passed, 6 skipped` | across **every file in the invocation**, summed |
| — | it does **not** say which file, and nothing in it hints that more than one was collected |

⇒ **Report a per-file result from a per-file run.** When you quote a count to another seat, quote
the invocation with it — or pass one file. A number lifted out of a multi-file run is a fact about
a set the reader cannot see.

⚠️ **THE COST LANDED ON THE PEOPLE WHO DID EVERYTHING ELSE RIGHT.** Both other seats reasoned
carefully from a number that was never about the file they were reasoning about — and one of them,
chasing it, produced the second half of this entry.

### 🔴 AND ITS COMPANION: A REAL MECHANISM AIMED AT THE WRONG TEST IS STILL A WRONG ANSWER

Mr. Radio 🦉, same evening, same thread, and the more expensive of the two errors.

Asked to explain that count, I read the guard and found something true: its third arm gates on
`_differs_from_head()`, so it **runs when an asset is dirty and skips when it is clean** — a
property of the working tree, not of the sha. I sent it as the explanation.

**It was true, it was confirmed by experiment, and it was about a DIFFERENT ARM.** The count in
question came from `followed_its_last_change`, which is insensitive to all of it — measured across
three tree states, one variable at a time: clean **4/5**, page dirty **4/5**, asset dirty **4/5**,
corpus **9** in every one (printed, not inferred from pass/skip counts).

⚠️ **NAME ONLY: `followed_its_last_change` was RETIRED 2026-09-04** (row `8af64f5a`, commit
`ed1cc008`) as redundant with `test_no_asset_changed_under_an_unmoved_token`, the census that
reports one failing id per unbumped change. **THE MEASUREMENT ABOVE STANDS EXACTLY AS TAKEN ON
2026-09-02** — a receipt records what was true when it was taken, and rewriting one to match
present code destroys the only thing it is for. This line exists solely so the name does not
send a reader hunting a test that is gone.
⇒ Identified as the PAGE-asset arm and **not** its `test_js_import_token_followed_its_last_change`
sibling — which survives, on a different corpus — by the corpus figure: **9** page assets then
(10 today; `task-verbs.js` joined at `5526d649`) against a JS-import corpus of **1**, which could
never print 4/5. A similar NAME is not a shared PREDICATE.

| I established | I never checked |
|---|---|
| the mechanism is real | that it reaches the test whose numbers were the question |

⇒ **This is § *THE OVERCLAIM HIDES IN THE JOIN* arriving from the inside.** I had measured both ends
— a real mechanism, a real discrepancy — and welded them without measuring the link. ⚠️ **And it is
worse than a wrong count, by this file's own ranking**: a wrong number gets re-derived by the next
reader, while **a wrong mechanism sends them into innocent code.** Here it sent a peer to build a
three-state experiment on the wrong variable.

⇒ **Before you offer a mechanism for someone else's number, ask which test produced that number and
whether your mechanism can reach it.** A mechanism that is true of the file is not thereby true of
the assertion.


---

## 🔴 `run-span=unmoved` keys on the sha, and the reader hears "the tree was clean"


The tier stamp is honest. Two fields sit on one line, answer different questions, and a reader collapses
them into a third claim neither makes.

| field | answers | does NOT answer |
|---|---|---|
| `run-span=unmoved` | did **HEAD** move during the run? (two `git rev-parse` samples) | did the **tree** change during the run? |
| `tracked-dirty=N` | is anything uncommitted, **at the end**? (`??` rows stripped) | **which file**, and do the tests read it? |

🔴 **Both are point samples, and no combination of point samples certifies a span.** The clean proof is
edit-and-revert: the tree genuinely changed and both endpoints agree, so no endpoint-based instrument can
ever see it — however many fields you add. A stronger endpoint (a content fingerprint) fails identically.

⇒ **The remedy is isolation, not a better detector.** A tree no other writer can reach cannot move
mid-run, so there is no span to certify. That is why *while a tier is running, that worktree is read-only*
is the control and these fields are only ever a report.

⇒ **Name a run by what it MEASURED, never by the sha you asked for** — `94ca3a0d + 24 uncommitted lines
in epic-stories.json`, not `94ca3a0d`. Six extra words, and the only true name.

⚠️ **`deleted=` names nobody at all** — a mount artifact and 125 real deletions print identically
(`+125-deleted` is a count wearing a path's costume). **Print the paths, not the count**; a flag a reader
must investigate to act on is a flag most readers will not act on.

⚠️ **A dirty tree is not automatically a kill — rule it, do not reflex it.** Re-firing costs the
comparability that made the greens mean anything. Say plainly what stayed unmeasured.

[receipts — the `epic-stories.json` incident, the `tracked-dirty=1` nobody read, the corrected first-row
claim, the TypeScript `deleted=125` mount census → doctrine/claim-construction.md]


---

### 🔴 AN EMPTY RESULT IS TWO DIFFERENT FAILURES WEARING ONE FACE


**You searched the WRONG population, or you searched an EMPTY one. The output is identical, and
nothing in it tells you which.** Four receipts in this file are the same defect.

| receipt | the population that was actually searched | what it looked like |
|---|---|---|
| the two-database trap (**directly below**) | `lupin_db_dev`, from a host shell chasing a `:8000` job | *"test_suite jobs are never persisted"* — false |
| the scoped `--cov` census (§100% COVERAGE MANDATE, *"A SCOPED `--cov` ANSWERS ONE QUESTION"*) | 61 files instead of 73 | twelve never-instrumented files read as **zero coverage** |
| the `pgrep -f` gate (*"IS ANOTHER SUITE RUNNING?"*) | every process whose **command line mentioned pytest** — including three seats whose briefing merely *discussed* testing | a gate that never opens, on an idle box |
| a `git grep` for a doctrine claim (2026-08-31) | tracked files only — and `io/post-games/` is **gitignored** | *"nothing on disk"*, from a search that could not see where doctrine lands |
| a `git grep -- 'src/docs/**/*.md'` (2026-09-01) | **17 of 35 docs — the SUBDIRECTORIES only.** A git pathspec is not shell globstar: `**/*.md` requires an intervening directory, so every file sitting DIRECTLY in `src/docs/` is silently outside it | zero hits, including a sentence the searcher had just read with their own eyes |

**The fourth is the clearest, because it took two people and neither had both halves.** Mr Radio
caught the wrong population — `git grep` cannot see untracked files. Maya caught that the
population was never verified — *no hits* and *no files* are byte-identical output. **Each of us
would have signed off on the other's search.**

⇒ **THE DISCHARGE IS TWO MOVES AND BOTH ARE CHEAP:**
1. **NAME the population** — the database, the `source` list, `comm` not the command line, the
   directory *and* whether your tool can see untracked files. Say it out loud in the command.
2. **PROVE THE SEARCH CAN FIND SOMETHING** — a positive control over the same corpus. A negative
   result is worth nothing until you have watched the instrument return a positive one.

Receipt: `grep -rl "masked-invariant" io/post-games/` returns 2 hits, so the same search returning
nothing for another string is now evidence rather than silence.

⚠️ **THE FIFTH ROW IS THE CHEAPEST ONE TO HIT AND THE HARDEST TO SEE — AND ITS POPULATION IS
PARTIAL, NOT EMPTY, WHICH IS WORSE.** The pathspec *looks* like the glob every shell has taught
you. Measured 2026-09-01: `git ls-files 'src/docs/**/*.md'` returns **17 files**, while
`git ls-files 'src/docs/*.md' 'src/docs/**.md'` returns **35**. The eighteen it drops are exactly
the ones sitting DIRECTLY in `src/docs/`, because `**/` in a git pathspec requires an intervening
directory. So the search runs, reads two thirds of the corpus, and reports a confident zero.

**A partial population is more dangerous than an empty one**: it returns plausible hits for other
searches, so nothing ever looks broken. The same regex that returned **0** across that pathspec
returned **1** when pointed at one of the excluded files directly. **The regex was never wrong.**
Nothing in git's output says so either — an unmatched pathspec is not an error, it exits 1, which
is indistinguishable from an honest no-match.

⇒ **Name the population as a COUNT before you trust a zero** — `git ls-files <pathspec> | wc -l`,
and sanity-check it against what you believe is there. `git grep -- 'src/docs/'` (a plain directory
prefix) is the form that does what you meant. (Swept 2026-09-01: **no committed script or test uses
the `**/*` pathspec form** — verified against a planted control line, so that zero is the tree's and
not the instrument's. This is a hazard for searches you TYPE, which is exactly where it bit.)

⚠️ **THIS IS NOT ONLY ABOUT SEARCH TOOLS.** It governs every absence-claim: a census, a coverage
zero-list, *"no rows matched"*, *"no other suite is running"*, *"that persona has no memento"*.
**Absence is the one finding that looks the same whether you did the work or not.**


---

### 🔴 AND THE MIRROR: A HIT IS NOT A USE — READ WHAT THE MATCH ACTUALLY DOES


The section above governs a result that is EMPTY. This one governs a result that is
FULL and still wrong: every line the search returned is a real match, and most of them
are not the thing you were asking about. **A grep finds the NAME. Your question was
almost always about the USE.**

**Three firings on 2026-09-01, in one evening, by three different people:**

| the search | hits | actual uses |
|---|---|---|
| test files naming `CLAUDE.md` | **81** | **8** open and read it — the rest are path strings and docstrings |
| unit tests naming `epic-stories.json` | 3 | **0** — one `monkeypatch`es `get_project_root()` and builds its own, one is a comment, one is the route string `/api/epic-stories` |
| guard message builders under `hooks/` | 4 mapped | **9** existed — the map that CLAIMED to be the frontier had never enumerated its own population |

⇒ **The middle row is the instructive one, because the correction ran the wrong way
first.** A warning was raised that a dirty config would contaminate a running tier; the
reviewer's own grep found a THIRD file and he began drafting it as a WIDENING of the
warning. Reading the three files instead reversed it: **none reads the real file, the
warning was groundless, and the "correction" would have made it worse.** Both parties
had grepped, and neither had read.

⇒ **The discharge is the same one sentence in both directions:** open the matches and
ask what the code does with them. This repo already states the rule — *"do not read a
bare import list as an exposure list"*, in § *A TIER RUN FROM A WORKTREE* — but it is
written there about imports and worktrees, so nobody reaches for it while typing a
`grep`. **It is the general rule, and this is where you were standing when you needed
it.**

⚠️ **The tell is that a NAME travels further than a USE.** A path appears in comments,
docstrings, route strings, error messages and other tests' prose; the code that opens
it appears once. So the ratio is lopsided by construction, and a population picked by
name is wrong by DEFAULT, not by accident.


---

### 🔴 AND THE THIRD FACE: A COMPLETE RESULT READ AS AN EXHAUSTIVE ONE — A CENSUS IS A FACT ABOUT A MOMENT


Pocholo 📣, 2026-09-03, caught by Rachel 🕊️ in a message I had already sent to the person who
was about to rule on it. **The two sections above govern a result that is EMPTY and a result
that is FULL-but-irrelevant. This one governs a result that is full, correct, relevant, and
still wrong — because the error is not in the search at all. It is in the TENSE.**

**The receipt.** A gate I had built refuses any actor carrying no session id, and `rick` is
such an actor. Asked whether that blocks him, I traced the client properly: **one** path to
`/transition`, **one** actor source, both read rather than grepped. Then I wrote it up as
*"nothing sends `actor=rick`"* — and that sentence is not what I measured. What I measured was
***nothing sends it today***.

| what I did | what I wrote |
|---|---|
| enumerated the population and found one member | *the population has one member* |
| — | ⇒ read by the next person as *the population cannot grow* |

⇒ **"I looked and found one" and "there can only be one" print identically in a summary**, and
only the second one closes the question. A reader who takes the second has no reason to look
again, which is the same disarming move as § *A WRONG REASSURANCE DISARMS THE READER* — reached
here not by vouching for something, but by quietly promoting a count into a guarantee.

🔴 **THE TELL IS THAT NOTHING PREVENTS THE SECOND MEMBER, AND NOTHING WOULD NOTICE ONE.** That
is the question to ask of any census you are about to state as a property: *what stops another
one appearing, and what would fire if it did?* Here the answers were **nothing** and
**nothing** — a second actor source is an ordinary afternoon's work, and the day it lands, a
hazard I had described as unreachable becomes reachable with no test, no alarm and no reader
going back to the sentence.

⇒ **So say what you counted and when.** *"One actor source in the client at `47cff912`"* is a
measurement. *"Nothing sends that actor"* is a claim about all future code, and I had no
evidence for it and did not need to make it. This is § *A COORDINATE IS NOT A REFERENCE*
pointed at your own findings rather than at your pointers: **a census carries a timestamp
whether you write one or not.**

⚠️ **AND IT LANDS ON THE RULING, NOT ON YOU.** A wrong count gets re-derived by whoever needs
it. An absence stated as a property gets *acted on* — here by a manager deciding whether a gate
was safe to merge, on a boundary I had drawn wider than my evidence. **The cost of this one is
paid entirely by the person who trusted it.**

⚠️ **Related, and the same evening, from the other direction — AND THIS PARAGRAPH HAS ALREADY
BEEN CORRECTED ONCE, WHICH IS THE POINT.** It first said the peer who caught this "re-derived
rather than let her figures be quoted at a new sha." She began to and was **stood down
mid-measurement** by the manager who owns the row. I had written the intent as though it were
the outcome — inside the section about exactly that — and she told me before anyone read it.

🔴 **WHAT SHE ENDED UP WITH IS A THIRD STATE AND IT IS WORSE THAN EITHER: HALF-REFRESHED.**
One side of her figure re-derived at a named sha and unchanged; the other side never reached,
still carrying the earlier one. **Her words, and they are the durable part: *"a worse state
than either, and I would rather say it than round it up."*** A fully stale figure is honestly
stale and a fully fresh one is honestly fresh; a figure with one side of each **reads as
refreshed** because the refresh is the thing you remember doing.

⇒ **So a partial re-derivation must be reported side by side, never as a single verdict** —
name which half moved, which half did not, and the sha each one carries. This is § *A TWO-FILE
INVOCATION CANNOT TELL YOU WHICH FILE THE RESULT CAME FROM* arriving on a measurement rather
than a test run: two provenances collapsed into one number nobody can take apart.

**Both halves of that evening are one discipline, and they fail in opposite tenses**: hers is a
measurement that may have aged, mine is a measurement I had written so it could never be seen
to age.


---

### 🔴 AND THE FOURTH FACE: A CORPUS CANNOT ANSWER "WHAT DOES THIS PROGRAM DO" — THE PROGRAM IS THE PRIMARY SOURCE AND THE ARTIFACTS ARE HEARSAY


Cheech 🌿, 2026-09-04. **The three faces above are about a search that returned the wrong population.
This one is about a search that could not have answered the question WHATEVER it returned.**

**The receipt.** Three seats spent an hour on **four corpus sweeps over 921 files**, asking whether a
value was frozen at write time or regenerated on read. **Every result was compatible with BOTH
mechanisms** — a corpus of outputs cannot separate *frozen* from *regenerated to a matching value*,
because the two produce the same bytes. **Two greps of the program settled it.**

⇒ **When the question is *what does this program do*, read the program.** The artifacts it produced
are hearsay: they are consistent with the behaviour you suspect, and equally consistent with every
other behaviour that would have emitted the same bytes.

🔴 **AND THE COST WAS WORSE THAN THE HOUR — THE SWEEPS MANUFACTURED CLAIMS THAT THEN HAD TO BE
RETRACTED.** A corpus result compatible with your hypothesis reads as support for it, so the wrong
instrument does not merely fail to answer: it hands you evidence. ⇒ *"The method is not the finding —
it is the cost."*

⚠️ **BOUND IT, OR YOU WILL THROW AWAY THE RIGHT INSTRUMENT.** A corpus is still exactly right for
**"what is out there"** — prevalence, blast radius, how many files carry the shape. Tiberius 👑's
**59/99** from that same evening survived every reversal in it, **precisely because it never claimed a
mechanism.**

| the question | the instrument |
|---|---|
| *how many · how widespread · what is affected* | ✅ the **corpus** |
| *why · which branch ran · frozen or regenerated* | ✅ the **program** — the corpus cannot discriminate |


---

### 🔴 YOUR MATCH KEY IS SHORTER THAN THE ROUTER'S KEY, AND THE MOST BELIEVABLE WRONG ANSWER NAMES THE ROUTE YOU WERE HUNTING


sam 🎙️, 2026-09-02. Measured at `8319ead2`, main checkout, `LUPIN_ROOT` and `PYTHONPATH` both
pinned, `PYTHONDONTWRITEBYTECODE=1`, 199 `Route` objects in the assembled app.

I wrote a check to find literal routes shadowed by an earlier parameterised sibling — the defect
behind `/api/tasks/flow-ratio` answering **422** all evening. **It reported seven. All seven were
false, and one of them was `/api/tasks/flow-ratio`.**

| arm | predicate | result |
|---|---|---|
| A | `par.path_regex.match( lit.path )` | **7 shadowed** |
| B | `par.path_regex.match( lit.path ) and ( lit.methods & par.methods )` | **0** |

**Starlette matches on path AND method.** A method mismatch is `Match.PARTIAL` — not a match, and
not a stop: the router keeps looking and takes the next route. My key was the path. Its key is the
pair.

**Four of the seven are plain method mismatches** — no overlap at all, so nothing further is needed
to dismiss them:

| literal | its method | the sibling's |
|---|---|---|
| `/admin/users/batch-delete` | POST | GET, DELETE |
| `/api/notifications/generate-gist` | POST | GET |
| `/api/websocket-sessions/single-session-policy` | PUT | GET, DELETE |
| `/api/cosa-voice/voice-persona/sample` | POST | GET |

🔴 **THE OTHER THREE ARE THE CENTRE OF THIS SECTION, AND `flow-ratio` IS WHY IT IS WRITTEN AT ALL:
`/api/tasks/{task_id}` IS REGISTERED TWICE.** Measured, in registration order:

```
idx 176  /api/tasks/{task_id}   PATCH   patch_task
idx 178  /api/tasks/events      GET     query_event_stream
idx 179  /api/tasks/flow-ratio  GET     get_flow_ratio
idx 183  /api/tasks/{task_id}   GET     get_task
```

⇒ The path-only arm compared `flow-ratio` against the **PATCH** twin at 176, which is genuinely
earlier — so the hit is arithmetically correct and semantically meaningless. **The GET twin, the
only one that could ever shadow it, is at 183 — after.**

**The discriminating reading, which is what settles it rather than the method table**: ask the
assembled app.

```
GET /api/tasks/flow-ratio  ->  resolves to  get_flow_ratio          # its own route
/api/tasks/{task_id} on that same scope  ->  Match.PARTIAL          # the PATCH object
```

⇒ **So the order is ALREADY CORRECT at this sha and there is no shadow here to find.** My check was
hunting a defect that had been fixed, and answered by naming the exact route I was hunting — which
is the property that makes this worth a section. **A wrong answer that names your suspect does not
read as a wrong answer. It reads as a confirmation.**

⚠️ **SCOPE, AND DO NOT WIDEN IT: this establishes that a path-only check over-reports IN THIS APP AT
THIS SHA. It does NOT establish that path-only checks over-report in general.** A same-method pair
registered in the wrong order **is** a real shadow, and **both** arms catch it — arm B is a
narrowing of arm A, never a replacement for it. A reader who takes away *"path-only checks
over-report"* will disable a check that works.

⚠️ **AND THE SECOND CAVEAT, WHICH IS THE TRANSFERABLE HALF**: the rule is not about routers. **It is
that a check and the thing it checks can agree on the field and disagree on the KEY** — and the key
is the part nobody states out loud, so both look correct. Ask of any check you write: *what does the
real system match on, and is my predicate the whole of it or a prefix?*

⇒ Related but NOT the same as § *A HIT IS NOT A USE* — there every match is real and merely
irrelevant. **Here the matches are computed, and wrong.** The population was right; the predicate
was short.

> 🔴 **THE TWO VENUES ALSO HAVE TWO DATABASES, and a host shell silently reads the wrong one.** Neither container sets `DB_NAME`, so each falls through to its own config block: `lupin-rest-dev` → **`lupin_db_dev`**, `lupin-rest-test` → **`lupin_db_test`**. A host shell inherits the *Development* block, so `PYTHONPATH=src python3` on the host queries **dev** even when the job you are chasing ran on `:8000`.
>
> **Measured 2026-08-28**, both directions inside a minute: host/dev returned **205 rows, zero `ts-` rows, nothing newer than the previous day**; the same query inside `lupin-rest-test` returned **4 rows, all same-day**, including the one at issue. The host answer reads exactly like *"test_suite jobs are never persisted"* — which is false, and a correct fix was one message from being retracted on it. **An empty result from the wrong box is not evidence; it is a confident answer to a question you did not ask.**
>
> ⇒ **Go at the database container and NAME the database** — `docker exec lupin-postgres psql -U lupin_dev -d lupin_db_test -c "..."`. Better than "run it inside `lupin-rest-test`", which still depends on standing in the right place — the thing that failed. **There is no default to fall through to**, verified both ways: a wrong name gives `FATAL: database "lupin_db_typo" does not exist`, and *omitting* `-d` errors too (psql tries the username as the database). You either name the box you meant or you are told. The in-container route lacks that property — it reads *a* database successfully either way.


---

### 🔴 A tier run from a worktree reports failures the main tree does not have


A worktree is `git`-identical to the main tree and **environment-identical to nothing**. Anything
gitignored, untracked, or exported into your shell is a property of *where you are standing*, not of
*what you are measuring*. **Subtract these; do not chase them.**

🔴 **`ls` first — the file is the coordinate and the count is derived from it.** Report presence as
attributes (`readable=yes lines=6`), never the words *present* / *absent*: a condensed message drops a
negation first, and this figure has been read back inverted. And use `-L` / `readlink` — every borrowed
artifact here is a **symlink**, so a bare `ls -l` reports the link's size, not the file's.

| missing | check | unit-tier failures |
|---|---|---|
| `src/scripts/cloud-run.env` (gitignored) | `ls -L src/scripts/cloud-run.env` | **9** absent · **0** present |
| `.venv` | `ls .venv/bin/python` | **33** |
| `src/terraform/envs/test/.terraform/providers` | — | 1 |
| `LUPIN_ROOT` left unpinned | — | 1 |

⚠️ **Provisioning runs in the PYTHON spawn path only** (`link-worktree-artifacts.sh`, row `dde8b87a`),
so a hand-typed `git worktree add` gets nothing and sees all of them. Run the script yourself there.

⚠️ **Subtract 43, never 44** — the extra red is a real held failure. Folding a genuine signal into an
artifact count is how it gets explained away by its neighbours.

⚠️ **"Imports `cosa`" is a risk indicator, not a verdict.** A test that asserts on a module's *behaviour*
is exposed; one that imports only a path helper and then reads FILES is not — `cu.get_project_root()`
reads `LUPIN_ROOT` at **call** time. Do not read a bare import list as an exposure list.

[receipts — five reconciliation passes across four seats, the arm tables, the `node_modules` isolation
→ doctrine/worktree-tiers.md]


---

### 🔴 A main-line red count must be run at the main line


A seat sweeping from its own branch is blind to exactly the defects its unmerged work repairs, and the
blindness is invisible from inside: the run is green, the tier is honest, and the number describes a tree
nobody else is standing on.

⇒ **A claim about "the tree" — a red count, a coverage list, a zero set — must be run at the main line,
or it is a claim about your branch wearing the fleet's name.** Same shape as a coverage list going stale
from a *merge* rather than a commit, and one step worse: a list that omits your work under-reports you,
while a red count that omits it **over-reports the branch's health**.

**Before running a tier from a worktree, pin all three — the first is inherited from your shell and
silently keeps naming the main repo:**

```bash
cd <worktree> && LUPIN_ROOT="$PWD" PYTHONPATH="$PWD/src" .venv/bin/python -m pytest src/tests/unit/ -q
```

🔴 **`LUPIN_ROOT` decides which tree paths RESOLVE against; `PYTHONPATH` decides which tree modules are
IMPORTED from.** Pin one and not the other and your run's modules come from **two checkouts — a tree that
exists nowhere on disk.** Measured: `lupin_app.*` from the worktree, `cosa.*` from the main repo, in one
pytest process. It points toward a **false green** — a mutation that never lands reads as a guard holding.

⚠️ Nothing is installed, so `sys.path` is the whole story, and for `cosa` the unit conftest's insert is
**inert**: `site` imports `sitecustomize.py` off `PYTHONPATH`, which imports `cosa` before pytest exists.
A symlinked `.venv` is **not** the culprit — the venv supplies no `cosa` at all.

⚠️ **A failure that passes in the main tree has TWO explanations** — a worktree artifact, or a fix you do
not have yet. `git merge-base --is-ancestor` only narrows the suspects; naming the commit closes it:
`git log --oneline <your-sha>..<main-HEAD> -- <the failing test's path>`.

[receipts — the 3-vs-4 reds at `dc96a65b`, the split-import-graph measurement, and the 10 / 11 / 43
reconciliations across four seats → doctrine/worktree-tiers.md]


---

### 🔴 And the worktree artifacts the tier cannot see — do not add these to the counts above


Same family — present in the main checkout, absent from every worktree, gitignored — but **none of them
reddens a test**, so folding them into that count corrupts it. **They fail in four different ways, and
the ranking is uncomfortable:**

| species | what it does | who investigates |
|---|---|---|
| a **red** (`cloud-run.env`) | failures naming the missing variable | everyone |
| a **refusal** (repo-root `.env` → `JWT_SECRET_KEY`, `jwt_service.py:35`) | the import raises | everyone |
| a **false fact** (`src/lupin_app/static/dist/`, 75 files, 0 tracked) | reports a live file as dead | whoever doubts it |
| 🔴 a **weakened check** (`websocket_smoke/config/baselines/`) | **passes, having compared nothing** | **nobody** |

⇒ **The set is computable, not discoverable** — a worktree contains exactly the tracked files at that
sha, so what git does not track is by construction what it lacks:

```bash
git ls-files --others --ignored --exclude-standard --directory
```

⚠️ **The judgement is in the filter, and it is the only place** — the enumeration is arithmetic;
deciding what counts as a cache is not. Say which figure you are quoting.

🔴 **Never symlink anything under `src/conf/keys/**` or the repo-root `.env` into a worktree, for any
reason.** A venv is a build artifact; a key is a secret, and a worktree gets `rm -rf`'d, copied and
shared. Subtract those knowingly instead. `node_modules` and `cloud-run.env` ARE borrowed by the spawn
path — the deny side is pinned by `test_no_borrowed_path_is_a_secret_or_a_build_output`.

⚠️ **The unit tier is immune to the `.env` refusal and the assembled app is not**:
`src/cosa/tests/conftest.py` does `os.environ.setdefault( "JWT_SECRET_KEY", … )` at **collection** time.
So 21,800 passing tests never notice, and only something importing `lupin_app.main` directly refuses.

[receipts — the 383,038 → 154 → 33 census, the `parity-harness.js` false fact, the three-people-one-evening
sequence → doctrine/worktree-tiers.md]


---

### 🔴 "Is another suite running?" — ask ownership, never a count


Two ways to get the process match wrong, pointing opposite directions:

| pattern | reported | truth |
|---|---|---|
| `pgrep -f "\-m pytest"` | 0 | missed a live run — the script form has no `-m pytest` |
| `pgrep -af "pytest"` | 5 | four spurious — **a seat's spawn briefing IS its command line** |
| `comm`-based (below) | 1 | ✅ |

```bash
ps -eo comm,args --no-headers | awk '$1=="pytest" || ($1 ~ /^python/ && $0 ~ / -m pytest/)'
```

`comm` answers *what this process is*; the command line answers *what someone wrote about it*.

🔴 **And a COUNT is unstable even off the correct command.** Over one unchanging run, 28 samples returned
**1** twenty-four times and **2** four times — the coverage gate spawns transient children. `… | wc -l`
then `-eq 0` cannot be made reliable by being careful. That is a correctness claim, not a diligence one.

⇒ **Ask ownership: is any pytest here NOT mine?** A transient child of your own run is still yours, so it
does not move the answer. Emit MINE / PEER / UNKNOWN per process, keyed on `/proc/<pid>/environ`'s
`LUPIN_ROOT` **or** `readlink /proc/<pid>/cwd` — **print which you used**, and emit **UNKNOWN** rather than
PEER when neither is readable. *"I could not tell"* and *"it is somebody else's"* are different facts.

🔴 **Fixing the tagger without fixing the gate changes nothing.** QUIET means zero PEER **and** zero
UNKNOWN — an honest three-state answer feeding a gate that still counts is the original defect one level
down.

⚠️ The both-unreadable branch is proven as logic, **never observed live**.

[receipts → doctrine/testing-venues.md]


---

### 🔴 A coverage list goes stale from a MERGE, not from a commit


Work in an unmerged worktree moves nobody's coverage but its author's. **Two correct numbers, two
different propositions:**

| question | ask |
|---|---|
| "Is my work done?" | the **worktree** — the tests exist and pass there |
| "Is the branch covered?" | **HEAD** — and it is not, until the merge lands |

⇒ **State the sha with the list.** A coverage list without its sha is a rumour with a timestamp — say
`at ef6e2bdc`, not "as of tonight". ⇒ **Report "done" and "landed" as separate columns.**

⚠️ **This governs every line-number citation you send a peer.** A bare `file.py:482` points into whichever
tree the reader is standing in. Write `file.py:482 @ 8bf71a64`; better, **cite the section heading or the
symbol name** — a heading survives an edit above it and a line number does not.

**The durable fix is a command, not a list** — anyone can re-derive the zero set at the sha they mean:

```bash
COVERAGE_FILE=/tmp/cov-$USER-$$.data LUPIN_ROOT="$PWD" \
  .venv/bin/python -m pytest src/tests/unit/ -q --cov-branch \
  --cov-report=term-missing --cov-fail-under=0
```

⚠️ **Run the WHOLE tier and do NOT pass `--cov=<path>` when the config defines `source`** — a scoped
override does not narrow the REPORT, it narrows what was ever MEASURED, and the difference is invisible in
the output. **Verify the config in the tree you are about to RUN IN, immediately before the run.**

[receipts — the retracted assignment, the 61-vs-73-file frame, the seven-vs-thirteen `source` count
→ doctrine/coverage-and-mutation.md]


---

### 🔴 A SCOPED `--cov` ANSWERS ONE QUESTION AND CANNOT ANSWER THE OTHER


Measured 2026-08-29. A narrowed scope — `--cov=<module>`, `--source=src/scripts` — does **not**
narrow the REPORT, it narrows what is ever MEASURED. Nothing in the output says so, and that is the
whole hazard.

| Question | Scoped run |
|---|---|
| *"What is THIS file's coverage?"* | ✅ **safe, if the file is inside the scope.** Per-file counts are scope-INVARIANT — the scope decides which files appear, never the numbers for one that does |
| *"WHICH files are at zero?"* | 🔴 **cannot answer it.** Use the project config |

**Why the second one bites**: absence from a scoped report is **not evidence of zero coverage — it
is evidence of never having been measured.** A census run this way returned thirteen files as
UNKNOWN, and unknown read as zero. Same shape as the two-database trap in §TESTING VENUES: **an
empty answer to a narrowed question is indistinguishable from a confident negative.**

**The receipt for the safe half** (this is why the rule is "use the project config for a census",
not "never scope"): `swe_workload_runner.py` was measured under two different scopes the same night
— `--cov=swe_workload_runner` and `--source=src/scripts` — and both report **163 statements / 0
miss, 44 branches / 0 partial**. Identical, because the file was inside both scopes.

⇒ **Scope freely while working a single file. Never scope a run whose output you intend to read as
a LIST.**

#### 🔴 AND A THIRD WAY TO MEASURE **NOTHING** WHILE EXITING 0

Found by Krishna 🦚 2026-08-30 as *"a `.py` path silently measures zero"*; both halves of that
moved under measurement, and the corrected rule is more useful than the original.

**`--cov=<target>` needs BOTH conditions, and fails identically when either is missing: the target
must be spelled as an IMPORTABLE module or directory, AND actually IMPORTED by the tests in that
run.** (Conjunction stated by Krishna 🦚 after the first rewrite — tighter than the two-case table
below, which is kept because it shows which condition each failure breaks.)
Two ways to land there:

| `--cov=` | result | why |
|---|---|---|
| a **`.py` file path** | **always zero** | nothing is ever importable under that name — fails 100% of the time |
| a **dotted module** your tests never import | **zero** | the form is right, the run simply never touched it |
| a **dotted module** your tests do import | correct | |

**Measured at `c91bd1bb`, one test file** (`test_replay_carries_the_requesting_user_id.py`):
`--cov=src/cosa/memory/solution_snapshot.py` → zero, while `--cov=cosa.memory.solution_snapshot`
→ `328 stmts / 262 miss / 82 branch / 17%`. And `--cov=cosa.rest.routers.notifications` → **also
zero**, dotted and well-formed, because that test does not import notifications.
`src.`-prefixed → zero as well; `src` is already on the path here.

⇒ **"Use the dotted form" is NOT the fix, and stopping at the path-vs-dotted framing would have
shipped a rule that still returns zero.** The fix is to check that the run you are about to trust
actually exercises the target.

⚠️ **IT IS NOT SILENT — three warnings fire, and the FIRST one names the file.** Calling it silent
was this reviewer's error, from a `grep -v warning` in the probe that stripped the evidence:

```
CoverageWarning: Module <target> was never imported. (module-not-imported)
CoverageWarning: No data was collected. (no-data-collected)
WARNING: Failed to generate report: No data to report.
```

**The hazard is the EXIT CODE, not the absence of a signal.** Coverage says exactly what is wrong;
the run still exits **0**, so a gate checking `rc == 0` passes on a run that measured nothing, and
a human reading a tail sees a clean finish among deprecation warnings.

⇒ **Read the coverage TABLE, and grep the output for `module-not-imported` before trusting a
number.** This is the third mechanism on this page producing a confident-looking nothing, alongside
the narrowed census and the two-database trap. **And note how this entry got its own count wrong —
a probe that filters warnings cannot report on warnings.**


---

### 🔴 COVERAGE MEASURES WHETHER A LINE **RAN**, NEVER WHETHER THE TEST COULD HAVE **NOTICED IT

RUNNING WRONG**

Measured three times in three files on one evening, 2026-08-30 (row `9124b70a`, Pocholo 📣 and
Maya 🌻). **Two of those files were at 100% lines and branches with the defect live in them.** The
coverage number was TRUE. It told us nothing.

**The defect**, identical in all three: a paged fetch asked for a flat `limit=PAGE_SIZE` whatever
cap the caller passed, so `--max-rows 100` fetched 500 rows and then announced *"truncated at 100
rows"* — the one figure whose job is to say how partial a scan was.

**Why every suite stayed green.** The fakes were `lambda *a, **k` — they returned their scripted
page WHOLE, whatever was asked. So the line executed on every run, was asserted around, and was
**unfalsifiable**: a capped request and an uncapped one produced byte-identical data.

```python
# BLIND — answers the same however the code behaves. Nothing downstream can recover.
monkeypatch.setattr( mod, "_request", lambda *a, **k: _page( rows, has_more=True ) )

# DISCRIMINATING — honours the input, so a wrong request yields a different observation.
def _request( method, url, api_key, timeout, body=None ):
    calls.append( url )
    return _page( available[ :_limit_of( url ) ], has_more=True )
```

⇒ **A test asks two questions and coverage only ever answers the first**: did the line run, and
*could the fixture have produced a different observation if the code were wrong?* A fake that
ignores its input answers **no** to the second by construction, and **every assertion written over
its output inherits that no.** The assertions here were not weak — they were correct, well-named,
and blind. **An assertion audit passes a blind fixture clean every time**, which is why re-reading
the test body is the wrong move.

🔴 **THE TELL, AND IT IS MECHANICAL:** *replace the code under test with a constant. If the fixture
still yields the same data, the suite is measuring the fixture.*

⚠️ **AND THE DISCRIMINATING CASE USUALLY NEEDS TWO CONDITIONS AT ONCE, WHICH IS WHY ONE FIX IS NOT
ENOUGH.** Measured: a fake that honours `limit` is still blind at `--max-rows 2000`, because
`min( 500, 2000 )` is 500 either way; and a cap of 2 is still blind against a 2-row page, because
both versions return 2. You need **a cap BELOW the page size AND a page LARGER than the cap.** A
seat told only *"assert on a small max_rows"* writes a test that looks like it covers this and does
not.

⚠️ **A related shape, opposite polarity — a fixture can also make a test ENDORSE the defect rather
than merely miss it.** Of the two landed copies, one asserted a result that *only the broken code
produces*; the other was merely blind. **Blind and endorsing are different**: the first goes green
on a correct fix, the second goes RED on one and reads as the patch having broken something. Check
which you have before concluding a fix is wrong.

**This is the fourth reading in § A MUTATION HARNESS CAN LIE, reached from the other direction** —
there, a surviving mutant sends you looking for a fixture that cannot discriminate; here, there is
no mutant and no red at all, only a coverage figure at 100%. **Same defect, and the coverage number
is the more dangerous entry point, because it arrives looking like an answer.**


---

### 🔴 Unguarded is a third state, and an assertion satisfied by two paths cannot discriminate


| state | the code | a test that could see it break |
|---|---|---|
| broken | wrong | — |
| **UNGUARDED** | **right** | **absent** |
| guarded | right | present |

⇒ **Say which one you are in, and prove it.** *"Detected"* asserts a live defect; *"fixed"* asserts one
that shipped. A field can be right and untestable-if-wrong at the same time, and neither word fits.

🔴 **Separate present-and-unwatched from absent MECHANICALLY, never by reading the guard**: delete it and
watch whether a NAMED test that was PASSING at baseline reddens. **A break list proves UNWATCHED; it never
proves ABSENT** — and the two want opposite fixes.

🔴 **The mechanism**: *a test whose assertion can be satisfied by more than one path cannot tell you which
path ran.* Ask of every assertion — **how many different states make this true?** More than one and the
test measures their DISJUNCTION, never the member you meant. **Name the path in the assertion**: the field
the guard populates, the branch it takes, the specific refusal it raises — not a downstream effect several
paths share.

⇒ **The fix is not a better assertion — it is a SECOND MEASUREMENT that kills one branch.** The rule above
tells you the reading is worthless; this tells you what to do next: go and eliminate a cause.

⚠️ **Count sufficient causes PER LEG, not per test.** A two-leg test can have two independent reasons to be
unfalsifiable, and fixing the one you spot reads like a repair while changing nothing.

[receipts — the demote guards, the approval-gate wiring check with two blind legs, and the five-test
closure at the HTTP layer → doctrine/coverage-and-mutation.md]


---

### 🔴 WHILE A TIER IS RUNNING, THAT WORKTREE IS READ-ONLY — WHATEVER YOUR REASON FOR TOUCHING IT


**Three receipts in one evening, 2026-09-02, from two seats**, which is why this is a rule and not
a note about one careless run. In every case the number produced was **about a tree that no longer
existed**, and in every case the seat threw it away rather than report it.

| seat | what moved | how it was caught |
|---|---|---|
| Rachel 🕊️ | her own edits landed mid-baseline | noticed while running |
| sam 🎙️ | applied a mutation at 17:49:09 while the tier was still writing at 17:49:18 | noticed while running |
| Rachel 🕊️ again | **two mutation arms editing `session_spawner.py` in place, tier at 27% in the same worktree** | **did NOT notice at the time** |

🔴 **THE THIRD ONE IS THE RULE, AND IT IS HERS: "DO NOT EDIT WHILE A TIER RUNS" IS TOO NARROW,
BECAUSE IT ONLY CATCHES EDITS YOU RECOGNISE AS EDITS.** A mutation arm *does not feel like
editing* — **it feels like measuring**, which is exactly how it walked past someone who had
written a paragraph about this defect minutes earlier.

⇒ **So state it about the TREE and never about your intent**: *while a tier is running, that
worktree is read-only.* No mutation arm, no "quick" fixture tweak, no thickening a guard, no
restore of a previous arm. **Your reason for touching it is not an input to the rule** — the run
cannot tell a measurement from an edit, and neither can the number it produces.

⚠️ **AND THE TWO FAILURE MODES ARE NOT EQUALLY SURVIVABLE.** *"I noticed I was standing in my own
measurement"* is recoverable — you discard and re-run. *"I did not notice, because the thing
standing in it was itself a measurement"* is the one that ships, because nothing about it feels
like the hazard you were watching for. **A rule keyed on intent cannot catch the case where the
intent is innocent.**

⇒ **The mutation numbers themselves can still stand** — Rachel's M7/M8 came from their own harness
against its own green baseline, not off the contaminated tier. **Say which instrument each number
came from**, and a contaminated tier costs you the tier and nothing else.


---

### 🔴 A WRONG COUNT PUBLISHES A WRONG NUMBER; A WRONG MECHANISM SENDS THE NEXT READER AT INNOCENT CODE


Derived 2026-09-02 when one TODO entry of mine was corrected on **both** at once, so the two costs
could be compared directly rather than argued about.

| what was wrong | what it costs a reader |
|---|---|
| the **count** — 4 disputes where 3 were genuine, one a RETRACTED claim | they quote a number off by one |
| the **mechanism** — *"the wake re-derives nothing at fire time"*, when it has re-derived since `8bf71a64` | they hunt a defect that is not there, **and find the working code instead** |

⇒ **The second is worse and it is not close.** A wrong number is corrected by a better number. A
wrong mechanism spends somebody's evening, and it spends it *plausibly* — the reader searches
exactly where you pointed, finds working code, and must then decide whether the code is fine or
their reading is. **That cost appears in no count, and it lands on whoever trusted you.**

⇒ **So rank your own verification that way.** When a claim carries both a figure and an
explanation, **the explanation earns the deeper check** — the figure gets re-derived by the next
person who needs it, and a mechanism that sounds right is not something anyone thinks to
re-measure.

⚠️ **AND WHEN YOU CORRECT ONE, SAY WHICH KIND YOU CORRECTED.** *"4 → 3"* reads as a population
shrinking. In the case above it was not: a retracted member came out **and an unrecorded
occurrence went in**, from the same seat in the same hour — the floor got *firmer*, not smaller.
**A bare corrected number teaches the opposite of what was learned, so state the direction, not
just the delta.**


---

### 🔴 A COMPARISON WHOSE TWO SIDES COME FROM ONE SOURCE CANNOT DISAGREE — AND IT LOOKS LIKE A TEST


Measured by Pocholo 📣, 2026-09-02, on a guard he was writing to close the wrong-corpus defect.
**It is not a blind fixture — it is one step worse, and the difference is worth holding.** A blind
fixture ignores its input; this one *honours* its input on **both sides at once**, so the two
sides move together and agree by construction.

**The receipt.** His corpus test compared *the files the walk found* against *the files it
expected*, and derived **both lists from the same exclusion set**. He added an exclusion expecting
RED — the standard falsification move, done correctly — and got **GREEN**: the walk shrank, the
expected list shrank with it, and the two agreed perfectly about **eight files that had just left
the frame**. The exclusion was real, the change landed, and the test could not see it.

⇒ **He did the right thing and it told him nothing.** That is what makes this worse than a blind
fixture: falsification is the check that catches blindness, and here **falsification itself came
back green**. A seat that stops at "I posed a mutation and it behaved" ships this.

🔴 **THE TELL IS STRUCTURAL AND YOU CAN SEE IT WITHOUT RUNNING ANYTHING: trace each side of the
`==` back to its origin. If they meet, you have a tautology wearing an assertion's clothes.** Ask
it of every comparison you write — expected-vs-actual, count-vs-count, list-vs-list.

⇒ **Fix by pinning ONE side to something the code under test cannot move**: a literal, a
committed fixture file, a hand-written count, a number derived from `git ls-files` when the thing
under test walks the disk. **The expected value must have a different provenance from the actual
one, or the comparison is an identity.**

⚠️ **AND THE COMPANION RECEIPT, FROM THE SAME FIX**: his corpus walk **missed eleven tracked
files** — the population defect reproducing *inside the guard written to close it*. Neither
finding was luck: both surfaced because he stated his denominator and made the corpus
**self-report on every run**. **A guard that prints how many files it scanned is a guard that can
be caught being wrong**; one that prints only pass/fail cannot.


---

### 🔴 A number that describes a gate must ASK the gate, not restate its rule


**Headroom is a PROJECTION of a gate, never a second gate.** The obvious implementation restates the
gate's comparison in a second place — often in a second language, across an HTTP boundary — and that is
two pieces of code deciding one rule.

🔴 **And the restatement is wrong before anything drifts.** The gate judges each create against the counts
**BEFORE** it lands, so the natural algebra `(created + N) / closed < allow_below` yields **one less** than
the gate admits. Writing it as a loop does not escape it: a loop probes the state after *k* creates rather
than the create itself. *Iterating is not the same as asking.*

⇒ **Hold no comparison of your own.** Call the gate advisory and count; raising `created` raises the ratio,
so the answer is monotone and a search over it is exact. **And borrow the caller's inputs, never re-read
them** — a live operator dial read twice a second apart gives two different worlds.

⇒ **When a projection replaces a sketch, check each of the sketch's states is still REACHABLE.** A state
that quietly loses its last input is a ratified decision disappearing without a ruling.

⚠️ **A projection describes the path it watches and nothing else** — exemptions and enforcement-off modes
are outside it. A displayed number that quietly widens its own scope is this defect in the caption.

⚠️ **A second INSTRUMENT earns its keep where a second opinion would not**: a brute-force walk caught a
`+1`-then-double probe that skipped 65 → 130 and returned 130 where the truth was 91. Every hand-written
case sat below the jump.

[receipt — the ratio-gate build, the 79-of-193 and 6-of-9 mutation arms, and Rick's ruled off-by-one
exception → doctrine/coverage-and-mutation.md]


---

### 🔴 TWO SIDES THAT DERIVE ONE VALUE BY DIFFERENT ROUTES ARE NOT AGREEING, THEY ARE COINCIDING — AND THE COMMON CASE IS EXACTLY WHERE THEY COINCIDE


sam 🎙️, 2026-09-02, measured at `8319ead2`. **§ *A COMPARISON WHOSE TWO SIDES COME FROM ONE SOURCE* describes a comparison that can never
disagree because its two sides share a source. This is the opposite arrangement with the same
result: two sides with genuinely different sources that happen to land on the same value nearly
every time.** A tautology is wrong by construction; a coincidence is right by circumstance, which
is harder to see and fails later.

**The case.** Two halves of the fleet's re-spin machinery answer the same question — *which repo's
data directory does this seat use?* — by two unrelated routes:

| | derives the root from | citation |
|---|---|---|
| **writer** (the boot receipt) | the **spawned seat's** repo | `register_session.py:1604` → `fleet_data_root( repo_root )` |
| **reader** (the wake watch) | the **firing manager's** ambient `LUPIN_ROOT` | `cosa_voice_mcp.py:3076` passes no `base_dir` → `respin_wake_check.py:777` → `:300-302` → `fleet_data_root()` no-arg → `heartbeat_hold.py:221` → `cu.get_project_root()` |

⇒ **They match whenever the manager and the worker are in the same repo, which is nearly always.**
Not by design and not by a shared constant — the two values simply coincide. Every test of the
normal case passes, and passes for a reason neither side states.

**What made it visible was a population with an empty complement**, not a failing test:

| data root | boot receipts | self-respin markers |
|---|---|---|
| lupin | 170 | 69 |
| lupin-mobile | 3 | **0** |
| planning-is-prompting | 12 | **0** |

⇒ Receipts distribute per repo; markers are **69 of 69** under one. And the zero carries its own
positive control — **the same directories that hold non-lupin receipts hold zero markers**, so the
instrument demonstrably reaches them. The mechanism confirms the census rather than being inferred
from it: `self_respin_core.py:778-780` also calls `fleet_data_root()` with no argument, and a live
read of the one non-lupin process on the box (MCP pid 313899) shows `cwd=/…/planning-is-prompting`
with **`LUPIN_ROOT=/…/lupin`**.

🔴 **AND HERE IS WHY A COINCIDENCE IS WORSE THAN A PLAIN DEFECT: THE OBVIOUS FIX BREAKS THE HALF
THAT WORKS.** The natural repair is to repoint the reader at the seat's own repo. That is right for
receipts. **For the markers it converts the coincidence into a defect in the other direction** — the
writer is the ambient one there, so a reader keyed on the seat's repo would stop finding markers it
finds today. **You cannot fix one side of a coincidence. You have to decide the rule and apply it to
every side at once.**

⇒ **So the question that finds this is not "do the two sides agree?" — they do, that is the
problem.** It is **"what would make them differ, and has that ever happened?"** Then go and look
there. Here the differing condition is a cross-repo spawn, the population is small, and nobody had
ever queried it.

⚠️ **THE TELL IS TWO DERIVATIONS, NOT TWO VALUES.** Whenever one fact is computed independently in
two places, write down what each one keys on. If the keys are different, the agreement you observe
is a fact about your inputs, never about your code — and the day the inputs diverge is the day you
find out.

⚠️ **WHAT THIS DOES NOT ESTABLISH, and the limits are the reason it is worth reading:**
- **No cross-repo spawn was run.** This is read from source plus one live environment read, not an
  end-to-end reproduction of the failure.
- **`LUPIN_ROOT` was read from ONE non-lupin process.** It is the only one on the box, so that is a
  sample of one against a population of one — not a survey.
- **Whether anything ever consumed those non-lupin receipts by another path is unknown.** What was
  established is what *this* reader does, nothing about other readers.


---

### 🔴 COVERAGE FOLLOWS THE BUTTONS A HUMAN HAPPENED TO PRESS, NOT THE ONES THAT CAN BREAK


Observed by Rio ⚡ 2026-09-02 on the task-list pane, generalised here. Ten mutations against its
controls, whole 484-test tier: **six scored ZERO** — `_controlScope` losing a leg, two controls
sending the wrong verb, and three blank-reason guards deleted, every one invisible.

**The two that DID redden are Won't-fix and Approve — the two Rick had actually clicked.**

⇒ **The suite had grown along the path of use.** Drop, Park and Demote were unguarded for no
reason more principled than that nobody had needed them yet, and a coverage percentage cannot
show you that, because **every one of those controls is fully covered**: the code runs, the lines
count, and no test could tell you if it ran wrong. This is § *COVERAGE MEASURES WHETHER A LINE
RAN, NEVER WHETHER THE TEST COULD HAVE NOTICED IT RUNNING WRONG*, with the selection bias named:
**what got exercised is a history of somebody's clicking, not a survey of the surface.**

⚠️ **It is the same defect as a guard pointed at the wrong corpus** — the stale `?v=` import that
no guard saw because every guard scanned HTML and the link lived in a `.js` file (same evening,
same crew). **There the population was chosen by file type; here it is chosen by usage.** Both
produce a confident green over the part nobody looked at, and in both the guards were *correct*
— they were simply aimed somewhere else.

⇒ **So enumerate the surface, not the traffic.** For a family of sibling controls, verbs or
endpoints, ask **how many exist** and **how many are watched**, and say both numbers. A guard
that cannot state its own denominator is telling you about its corpus, not about your code.


---

### 🔴 WHEN THE FIX FOR AN ENUMERATION DEFECT IS ITSELF AN ENUMERATION, YOU HAVE MOVED THE DEFECT, NOT CLOSED IT


Maya 🌻 and María 🌸, 2026-09-05, measured across one module over one afternoon. **A
hand-maintained list fails the same way every time — correct for everything the author thought
of, silently wrong for everything else — and the reflex repair is to write a better list.** That
repair inherits the whole defect and looks like a fix, because the new list is right about
everything you just tested.

**FIVE INSTANCES IN `src/scripts/dead_rnd_citations.py` ALONE, and three of them are repairs of
the two above them:**

| # | the enumeration | what it could not see | replaced by |
|---|---|---|---|
| 1 | a fix-marker sha **hardcoded to one value** | 40 sites annotated, only 15 stopped being reported | the marker's own shape |
| 2 | a **four-name** cross-repo prefix tuple against **fourteen** registered repos | correct citations flagged dead | the repo list **derived** from `lupin-app.ini` |
| 3 | an enumerated **separator list** (`→`, `` ` ``, `>/`) | 22 non-slash forms against 4 shapes; special-casing `→` fixes 8 and *looks done* | **any short run** of separator characters |
| 4 | a hand-written **"continues a filename" character class** | whatever character the author omitted | `(?!\w)` |
| 5 | the guard's own **`[a-z|]+` extraction class** | 🔴 **the very extensions it was written to catch** | the alternation read from the pattern itself |

🔴 **ROW 5 IS THE ONE TO SIT WITH.** It is inside the *guard* — the artifact whose entire job was
to stop this defect — and its class could not match the thing it was guarding. **A hand-written
character class is a hand-maintained enumeration of CHARACTERS**, and nothing about the smaller
scale makes it safer.

⇒ **THE DISCHARGE IS ONE QUESTION, ASKED BEFORE YOU WRITE THE LIST: what PREDICATE is this
enumeration approximating?** Then write the predicate. *Any separator run*, not four separators.
*Not a word character*, not eleven characters. *The repos the config registers*, not the four you
remembered. A predicate cannot go stale when the world grows a fifteenth member; a list can only
be wrong in a direction nobody is watching.

⚠️ **AND A PREDICATE CAN REST ON A PREMISE, WHICH IS AN ENUMERATION IN HIDING.** `(?!\w)` is
exactly `\b`'s trailing half **only while every alternative in the extension list ends in a word
character** — true today (`md py sh json txt`), and an edit away from false (`c++`, `sh-`). The
equivalence is structural, not empirical, and **the premise is the thing that can be edited out
from under it**. ⇒ Pin the premise with its own guard
(`test_every_extension_ends_in_a_word_character`), or you have swapped a visible list for an
invisible one.

⚠️ **SCOPE, stated so nobody over-reads it**: five instances, **one module**, one afternoon, most
of them the same author's. That is a shape worth recognising, **not** a measured frequency across
the tree — nobody has swept for it. What makes it worth a section is not the count but that
**instances 3, 4 and 5 were each written as the FIX for the instance above**, by someone who had
just been bitten and was actively trying not to be.

⇒ Same family as § *AN EMPTY RESULT IS TWO DIFFERENT FAILURES WEARING ONE FACE* and § *A HIT IS
NOT A USE*: all three are a **population chosen by hand** standing in for the population you
meant. Here the hand-chosen set is not the search corpus but the *rule itself*.


---

### 🔴 THERE IS A SECOND VIRTUALENV *INSIDE* `src/`, AND IT IS 92% OF EVERY DISK SWEEP


`src/cosa/.venv` is a full vendored virtualenv living inside the source tree. Measured 2026-08-30:

| population | count |
|---|---|
| `find src -name '*.py'` | **31,734** |
| of which `src/cosa/.venv` (3.11 vendor) | **29,303 — 92%** |
| `git ls-files 'src/**/*.py'` | **2,415** |

It is **untracked and ignore-matched**, which is exactly what decides who it fools:

- **git-derived** sweeps (`git ls-files`, `git grep`) never see it and are **correct as-is**.
- **disk-derived** sweeps (`find`, `rglob`, `compileall`, an unscoped `--cov`, a bare `grep -r`) see
  it and are **inflated ~13×** with third-party code for an interpreter this repo does not run.

**Receipt for why this is not theoretical**: the first cut of `migrate-pyc-to-checked-hash.sh`
targeted `src/` with `rglob`, spent 40+ seconds rewriting vendored 3.11 bytecode, and reported
"30,621 converted" — a five-figure number that read like a thorough migration and was 92% a fact
about somebody else's code. The honest figure was 1,318. Excluding the venv cut the run to 3.5s.

⇒ **Any tree-wide operation must exclude `.venv` / `node_modules` / `site-packages`, or be
git-derived.** This is the same lesson as the collision guard on row `c89cec9b` from the opposite
direction — there, disk-derived counting *added* a machine-local leftover; here it adds 29,303
vendored files. **Ask what population your command actually walks before you read its number.**


---

### 🔴 AND `--bg` MAKES THE EXIT CODE MEANINGLESS BY DESIGN — THE MANDATE ABOVE GUARANTEES THE FALSE GREEN


Rio ⚡, 2026-09-06, re-derived at `356a9959`. **The rule directly above is not merely
compatible with a false green — on two of its three suites it produces one every single
time.** `--bg` backgrounds the run with `nohup`, prints the monitoring instructions, and
**exits 0 before pytest exists**:

| suite | `--bg` handling | what the launcher's exit code means |
|---|---|---|
| `src/scripts/run-e2e-ui-tests.sh` | `exit 0` at **`:103`** | 🔴 **nothing** — always 0, whatever the run does |
| `src/tests/run-integration-tests.sh` | `exit 0` at **`:101`** | 🔴 **nothing** — same shape |
| `src/tests/run-presentation-regression.sh` | **`--bg` is a NO-OP** (`:70`, *"stripped by test-suite job"*) | ✅ **real** — it runs in the foreground and returns pytest's code |

⇒ **The third row is why this is a table and not a sentence.** Two of the three
early-exit and one does not, so *"a `--bg` launch returns 0"* is true of the suites people
actually reach for and false of the one that looks identical on the command line. **A rule
stated across all three would be wrong about a third of its own population.**

🔴 **THE LAUNCHER'S EXIT CODE AND THE RUN'S EXIT CODE ARE DIFFERENT NUMBERS, and only one
of them is ever visible to the caller.** `run-e2e-ui-tests.sh` is otherwise textbook —
it captures `PYTEST_EXIT_CODE=$?` and re-raises with `exit $PYTEST_EXIT_CODE` at the end.
**That correct code runs in the BACKGROUND child**, whose status nobody collects. What the
foreground caller reads is the launcher saying *"I successfully started something."*

⇒ **FOR A `--bg` SUITE THE EXIT CODE IS NEVER EVIDENCE. READ THE LOG.** The summary line
(`N failed, M passed`) and the `FAILED` lines are the finding; `/tmp/e2e-ui-latest.log`
and `/tmp/integration-latest.log` are where they land.

⚠️ **This is § *A CLEAN EXIT IS NOT EVIDENCE THE WORK HAPPENED* with the clean exit made
MANDATORY.** Every other member of that family is an accident — a tool no-ops, a wrapper
swallows a status. Here the exit-0 is correct behaviour for backgrounding, the mandate
above *requires* the flag that triggers it, and the two combine into a guaranteed green
that no one wrote and no one can fix by being careful. **The doctrine and the script are
each right; the pair is what fails.**

⚠️ **AND IT EXONERATES THE HARNESS, WHICH IS THE HALF THAT NEARLY WENT THE OTHER WAY.**
An unexplained EXIT-0 sighting was read as a possible harness defect. It is not: both
submission doors refuse loudly and legibly — `ts-b1c77004` reported *"COLLECTION ERROR —
the suite did not run"* and `ts-b6968dda` reported *"NOT EXECUTED"*. The 0 came from the
launcher, by design. ⚠️ A wrapper hypothesis aimed at `run-e2e-ui-tests.sh`'s capture-and
-re-raise was **wrong and is withdrawn** — that code is correct, and blaming it would have
sent the next reader into innocent lines.


---

### 🔴 THE LINE YOU ADD TO REPORT THE EXIT CODE IS THE LINE THAT DESTROYS IT


Two seats launched background tiers on 2026-09-01 and both were reported as **exit code
0** over a pytest that had exited **1**. The first reading was that the harness
mis-reported. It does not — a bash command's status is its LAST command's, and the
wrapper shape everyone uses ends in something else.

**Measured, one variable per arm:**

| command | wrapper status |
|---|---|
| `false` | **1** ✅ |
| `false; tail -0 /dev/null` | 0 |
| `false; echo "EXIT=$?"; true` | 0 |
| **`false; echo "EXIT=$?"`** | **0** 🔴 |
| **`false; rc=$?; tail …; exit $rc`** | **1** ✅ the fix |

⇒ **The fourth row is the one to look at.** The `echo "EXIT=$?"` added *specifically to
surface the exit code* is by itself enough to replace it — the diagnostic destroys the
thing it reports. The log tail is not the culprit and removing it fixes nothing.

⇒ **Capture immediately, re-raise at the end:**

```bash
pytest src/tests/unit/ -q > /tmp/tier.log 2>&1; rc=$?; tail -20 /tmp/tier.log; exit $rc
```

⚠️ **And the exit code was never the evidence anyway** — read the summary line
(`N failed, M passed`) and the `FAILED` lines. This is § *A CLEAN EXIT IS NOT EVIDENCE*
reached from its other side: there, a tool exits 0 having done nothing; here, a wrapper
exits 0 over a tool that did the work and failed. **Both hand the caller a green that
nothing supports**, and in both the fix is to read the tool's own account.

**Coverage**: `pytest --cov=cosa --cov-report=html src/tests/` (Python). See §100% COVERAGE MANDATE for the hard gate.

**Editing a `.py` file inside a test?** Use `tests.helpers.pyc_freshness` (`mutate_source` fixture / `refresh_source`). CPython validates a `.pyc` on the source's **whole-second** mtime **plus size**, so a mutation edit changes neither and the interpreter keeps running the *old* code after you restore the file and read it back — measured twice on 2026-08-29, on `job_state.py` and on the helper's own module (row `d18ce9ef`). ⚠️ `PYTHONDONTWRITEBYTECODE` does **not** fix it; it only stops pycs being *written*. Debugging a red you cannot explain? Run **`src/scripts/purge-pycache.sh`** before concluding anything. 🔴 **NOT a raw `rm -rf __pycache__` — that now RE-OPENS the very hole it used to plug** (row `866f43ce`, §100% COVERAGE MANDATE below): the tree is on checked-hash invalidation, a pyc written where none exists is timestamp-based, so a bare purge silently reverts the tree with nothing in any output saying so. The script purges **and** reconverts, ~3.5s, and **checks it can reconvert BEFORE it deletes anything** — no interpreter means exit 2 with nothing removed. ⚠️ It did not always: until `4119447b` it purged first and discovered the missing interpreter after, on the **35 of 80 worktrees** with no `.venv/bin/python`, leaving the tree exactly as this paragraph forbids. The preflight removes that cause; it does not make a reconvert that fails *midway* impossible, so read the exit code. ⚠️ **The two scripts documented in this paragraph do not share a flag surface**, and the read-only one belongs to the other script: `--verify` is `migrate-pyc-to-checked-hash.sh`'s, while `purge-pycache.sh` takes only `--dry-run` (and `-h`). Naming this because the mix-up actually happened — a seat was told to run `purge-pycache.sh --verify` for a read-only report, which before `3e0c2cdc` would have silently performed a full purge instead. **Neither script resolves its tree from `$LUPIN_ROOT` any more** (`5e7f74e8`): both derive it from their own location, so a `LUPIN_ROOT=…` prefix on either command now does nothing — run the copy that lives in the tree you mean. Detail: `src/tests/README.md` § EDITING A SOURCE FILE INSIDE A TEST, measurement `src/rnd/v0.2.1/2026.08.29-stale-pyc-defeats-mutation-testing.md`.

**Docs**: `src/tests/README.md` (overview), `src/tests/integration/README.md`, `src/docs/automated-interactive-testing.md` (proxy), `src/tests/smoke/README.md`, `src/tests/AUTH-TESTING-GUIDE.md` (credentials), presentation strategy `src/rnd/v0.1.6/2026.03.14-presentation-generator/2026.04.07-e2e-testing-strategy.md`.


---

### 🔴 A mutation harness can lie in both directions — read a survivor four ways


**Take a GREEN baseline FIRST and record the failing set.** The kill signal is the failing SET, never the
exit code: **killed iff a NAMED test that was PASSING at baseline now fails.** `rc` 4/5 mean pytest could
not RUN the node. And on a branch carrying a deliberate red the suite exits 1 before any mutation is
applied, so `rc == 1` scores every mutant as killed — a 14-arm pass read 14/14 where it was 9/14.

⚠️ **A failing SET compares test IDs, and an id says nothing about WHY.** Compare the assertion that
fired. And **an assertion added behind a currently-failing one is carried, not exercised** — the id is
byte-identical whether it passed, failed, or never ran. Put a new guard in its **own test**.

**Every mutation asserts it APPLIED** — the anchor matched exactly once, the on-disk sha CHANGED — plus a
restore control at the end that is actually READ.

🔴 **Isolate every arm.** The requirement is that nothing carries between arms:

| form | strength |
|---|---|
| rebuild the sandbox per arm | ✅ strongest — nothing survives by construction |
| `src/scripts/purge-pycache.sh` between arms | good, and the practical choice in a working tree |
| a raw `find … __pycache__ -delete` | 🔴 **re-opens the defect** — the rebuilt pycs are timestamp-based |

**A SURVIVING MUTANT HAS FOUR EXPLANATIONS. Separate them before writing a line of test code:**

| explanation | how to tell | cost of getting it wrong |
|---|---|---|
| a **weak test** | the other three are ruled out | the only one that earns a new test |
| a **broken harness** | re-run that ONE mutant by hand — if it reddens, the harness lied | you accept a false ceiling |
| an **equivalent mutant** | read the edit: did it repair its own damage? | you test something that was never a defect |
| 🔴 a **fixture that cannot discriminate** | read the **DATA**, not the assertions | you audit correct assertions, find nothing, conclude the code is fine |

⇒ **The fourth is invisible to a careful re-read of the test body.** If two quantities can be exchanged
without changing the expected output, the test asserts their SUM, not their identity — whatever its name
says. Fix the FIXTURE, never the assertions.

⚠️ **A clean pass samples the mutation space; it does not survey it.** Two harnesses on one file find
different things. A cross-harness sha match proves only **edit identity** — exchange shas to catch a
disagreement, never to manufacture a confirmation.

⇒ **"I repaired a fixture" is not "I proved the repair discriminates."** Two arms off ONE mutated sha: the
OLD fixture SURVIVES, the NEW one is KILLED by the named test. Neither arm alone counts.

⚠️ **Put a CEILING on a kill count, not only a floor.** A break aimed at one line should redden the tests
reaching that line — **a kill at or near 100% of the corpus is a syntax error until proven otherwise.**
Compare the RUN count against baseline, not just the failure count: `0 passed / 48 failed` and
`0 passed / 0 failed` are different worlds and both begin `0 passed`.

[receipts — the rc=4 false kill, the stale-bytecode both-ways measurement, the four worked survivor
examples, the three clean two-arm instances → doctrine/coverage-and-mutation.md]


---

### 🔴 Pyc invalidation — both scripts resolve a tree you may not be standing in


The tree is on **checked-hash** invalidation (Rick's ruling `866f43ce`, 2026-08-30). Otherwise CPython
validates a `.pyc` on the source's whole-second mtime **plus size**, so a mutation changing neither runs
the *previous* arm's bytecode — faking both survivors and kills.

| script | does | flags | tree it acts on |
|---|---|---|---|
| `migrate-pyc-to-checked-hash.sh` | converts, or reports | `--verify` (read-only) | 🔴 **`$LUPIN_ROOT/src`** — your shell's, not your cwd |
| `purge-pycache.sh` | purges **and reconverts** | `--dry-run` only | its own location; `LUPIN_ROOT` is **inert** since `5e7f74e8` |

⇒ **Run the copy living in the tree you mean.** For the verifier pin both — `PYTHON` derives from
`LUPIN_ROOT`, so pinning only the root aims the interpreter at a venv the worktree lacks:

```bash
LUPIN_ROOT="$PWD" \
PYTHON="$( dirname "$( git rev-parse --path-format=absolute --git-common-dir )" )/.venv/bin/python" \
  ./src/scripts/migrate-pyc-to-checked-hash.sh --verify
```

**Read its `scanned roots:` line, not its checkmark** — an unpinned run blesses the main repo and
prints a verdict about a tree you are not testing.

| exit | meaning |
|---|---|
| 0 | every pyc this interpreter reads is checked-hash |
| 1 | ✅ the real finding — timestamp pycs present |
| 2 | **it never ran** — bad option · root not a directory · **no interpreter at `$PYTHON`** (~2 in 5 worktrees have no `.venv`). stderr is the only discriminator |

**Three states, and the first and third both print `0` meaning opposite things:**

| tree | `--verify` | means |
|---|---|---|
| fresh, never used | 0 | 🔴 **vacuous — nothing there to judge** |
| fresh, then one ordinary run | 1 | timestamp pycs, written where none existed |
| converted **and** populated | 0 | ✅ genuine — an ordinary pytest run does **not** undo it |

⇒ **Use a new worktree once, purge-and-reconvert, then verify.** A verify on an unused tree is not evidence.

🔴 **A raw `find … __pycache__ -delete` re-opens the hole it used to plug** — a pyc written where none
exists is timestamp-based. Use `purge-pycache.sh`, which refuses before deleting if it cannot reconvert.
**And `-f` is the whole migration**: without it `compileall` treats an up-to-date pyc as needing no work
and converts nothing while reporting success.

⚠️ `PYTHONDONTWRITEBYTECODE` suppresses *writing*, never *trusting*. Editing a **test** file inside a test
still needs `tests.helpers.pyc_freshness`. **Never mutate in a peer's live worktree — or in the shared
main tree**; check the sha out into a detached worktree of your own. A `cp` restore from your own backup
carries the same race as the `git checkout` you were told to avoid.

[receipts — the three-tree census, the four-seat reproduction, the wrong-tree purge incident, the
venv-less ratio → doctrine/coverage-and-mutation.md]


---

### 🔴 Two fixture defects that wear a costume


**A fixture defect can look exactly like the defect under test.** When a fixture change produces precisely
the failure a test was written for, suspect the **fixture** first: you have just introduced a second cause
for one observable. The wrong reading — *"my re-pointed fixture reddens, so I found a bug in their code"* —
is available and comfortable, and a weaker test would have let you publish it.

**A hand-written fixture is systematically better-formed than reality, exactly where a parser depends on
the mess.** Measured: `_git_reader` strips its whole output, which removes the leading space from the
**first** porcelain line only — so that line needs `line[2:]` and every other needs `line[3:]`. A person
writing a fixture writes a well-formed line, so every synthetic case passed and the real input failed.

⇒ **The tell is that the fixture never went through the pipe.** A test that constructs its input tests the
parser against your *model* of the producer; where the two differ, the test agrees with your model — and
your model is what was wrong, or there would be no bug.

⇒ **For any parser, capture at least one fixture FROM THE REAL PRODUCER, THROUGH THE REAL READER**, and
commit it. One is enough to catch a whitespace, encoding, line-ending or ordering assumption.

⚠️ **Neither half was wrong on its own** — `line[3:]` is right for porcelain, the `strip()` is reasonable
for a command reader. Reading either file in isolation exonerates it.

[receipts → doctrine/coverage-and-mutation.md]


---

### 🔴 When reporting damage to an artifact, describe what is PRESENT, not what is missing


A truncated artifact carries no note saying how much did not arrive: **the reader cannot tell there was
more, and the writer cannot tell it was not received.**

| the claim | checked against | available to you? |
|---|---|---|
| **presence** — *this is here* | **the artifact** | ✅ it is in front of you |
| **absence** — *that is missing* | **your intended content** | 🔴 no — that reference is what was already wrong |

⇒ **An author reads their own artifact through the plan that produced it**, so the damage is concealed
worst from the one person looking straight at it. *"Go and look at it"* is not the remedy — looking is
what they did. **Compare the artifact against something other than your intention for it.**

⇒ **Practical form**: for anything that renders or transmits, make truncation loud at the receiving end —
a length, a terminator, a "continues" marker. Where you cannot, treat an artifact ending mid-structure as
**content of unknown size** and go back and ask.

⚠️ Held at n=1, self-reported. **What would kill it**: a pure presence claim about a malformed artifact
that still comes out wrong.

[receipt — the four-post reconstruction, the correction-post that repeated its own subject, and the
controlled framing pair → doctrine/claim-construction.md]


---

### 🔴 A FINDING FILED AS A STATE, WITH NO OWNER, READS AS CLOSED — AND ACCEPTING IT WITHOUT MINTING A ROW IS DEFERRAL WEARING ACCEPTANCE'S CLOTHES


Rio ⚡ and María 🌸, 2026-09-02, both halves reproduced independently. **Six tests went red in a
merge, sat for hours, and surfaced as a merge-gate failure — and at no point was anybody unaware of
them.** That is what makes this worth a section: nothing was hidden, nothing was missed, and the
work still went unowned.

**Measured per sha, counting the handler the guard slices out of the client source against the count
the guard expects:**

| sha | `js_defines` | `test_expects` | |
|---|---|---|---|
| `8319ead2` | 1 | 2 | **GREEN** — the guard existed and passed |
| `d49a6ba6` | **0** | 2 | 🔴 **RED, born here** — *"Five buttons and five boxes become one select, one field and one Submit"* |
| `46a3078c` | 0 | 2 | unchanged |
| `038c019d` | 0 | 2 | unchanged |

⇒ **The author reported them AT that sha** — *"6 red / 34 pass, all six pinning old names"* — a
correct and complete classification. **The reviewer read it, accepted it in writing, and merged.**
Then it sat, until an unrelated tier turned it into a gate failure hours later.

🔴 **THE TWO HALVES, AND EACH IS SUFFICIENT ON ITS OWN:**
- **Filed as a STATE**, a finding is a fact about the tree — true, durable, and addressed to nobody.
  **A fact does not appear on anyone's board.**
- **ACCEPTED without a row**, the acknowledgement discharges the obligation to *respond* and creates
  none to *act*. ⇒ *"Acceptance without an owner is deferral wearing acceptance's clothes."*

⇒ **SO A RED YOU ACCEPT IS A ROW YOU OWE.** Not a note, not a DM, not a line in a merge report — an
item with an owner and a status, minted at the moment you accept it. **If a finding is real enough
to accept, it is real enough to carry a name.**

⚠️ **THE TELL IS THAT EVERY INDIVIDUAL STEP LOOKS DILIGENT.** The author measured. The reviewer
read. Both were right about the facts. **What is missing has no step of its own**, which is why it
never fails a checklist — the gap sits between *classified* and *owned*, and neither artifact points
at it.

⚠️ **AND HOW THIS ENTRY WAS CORRECTED, because that is a receipt too.** It first published a
different account: *a scoped green (542/542, TypeScript-only) could not see a Python guard reading
the same source as text.* **That is not what happened.** The red was not invisible to a narrow
suite — it had already been read and accepted, and the guard file existed and passed one sha
earlier. The reviewer retracted her own account within minutes, per-sha, after the author corrected
her, and did so while it was already committed under her name.
⇒ **The scoped-boundary rule may well be true; it has no receipt in this incident, so it is not
recorded here.** A rule welded to the wrong evidence is worse than no rule — it sends the next
reader to defend a suite's scope when the real defect was that nobody owned a red everybody knew
about.


---

## 🔴 A MEMENTO HAS TWO SLOTS, AND THE TWO DOORS READ DIFFERENT ONES


**This is not a defect and it is not a fallback.** `self_respin` reads the **root** slot;
`dismiss_sessions` (the reap) reads **io**. Written down here because it was filed as a bug on
2026-08-30 (row `f74d226a`, dropped as invalid) by a seat that had the measurement right and the
diagnosis wrong — a memento written to `io/` was refused by `self_respin`, which is the code doing
exactly what it says.

| Door | Slot | Pointer | Record |
|---|---|---|---|
| `dismiss_sessions` — a manager reaps a seat it **SPAWNED** | `io` | `io/mementos/<persona>.md` | `io/mementos/<persona>-<sid8>.md` |
| `self_respin` — a manager clears its **OWN** pane | `root` | `.claude-memento-<persona>.md` (**per-persona since 2026-09-02**) | `.claude-memento-<persona>-<sid8>.md` |

**Write with the slot named** — the writer lands record, mirror and pointer in one operation, and
picking the slot is the whole decision:

```bash
python3 $PLANNING_IS_PROMPTING_ROOT/workflow/scripts/memento_io.py write --slot root   # you are about to self_respin
python3 $PLANNING_IS_PROMPTING_ROOT/workflow/scripts/memento_io.py write --slot io     # a manager is about to reap you
```

**Source of truth, cited rather than restated** — `SELF_RESPIN_SLOT = SLOT_ROOT` at
`src/lupin_mcp/memento_slot.py:83`, whose comment calls the split *"a DELIBERATE disjointness, not
a coincidence"*; `reap_memento`'s module docstring is the authority on which door owns which slot.
The check is wired, not decorative: `src/lupin_mcp/self_respin_core.py:572` defaults the
`verify_slot_fn` seam to `_default_verify_slot` and line 597 calls it on the live path.

🔴 **THE ROOT POINTER WAS PERSONA-LESS UNTIL 2026-09-02 AND IS NOW PER-PERSONA. THE MEASUREMENT
BELOW STANDS; THE LAYOUT IT DESCRIBES DOES NOT.** Measured 2026-08-30, when `.claude-memento.md` was
one file shared by every persona: Pocholo wrote `--slot root` at 14:41 and took the pointer, Mr.
Radio wrote at 15:20 and took it back. Step 3 (`planning-is-prompting@00fac2b`, Rick's
authorisation) moved the writer to `.claude-memento-<persona-slug>.md`, so **cross-persona theft of
the pointer is gone by construction** and the shared file is a frozen leftover nothing refreshes.

⚠️ **THE VERIFIER'S SECOND LEG SURVIVES THE CHANGE, FOR A DIFFERENT REASON THAN IT WAS BUILT FOR —
AND THAT DISTINCTION IS THE POINT.** It re-reads the pointer's own header `session_id` rather than
trusting placement. Its original justification was the cross-persona handoff above, which is now
dead. What keeps it load-bearing is that **a persona outlives its sessions**: `.claude-memento-mr-radio.md`
written by one session is followed by the NEXT session of the same persona, so a stale pointer still
names a `session_id` that is not the reader's. ⇒ **A correct conclusion resting on a retired premise
is not the same as a correct conclusion.** Say which one is holding it up, or the next person to
retire the premise deletes the leg with it.

✅ **CLOSED 2026-09-04 (Cheech 🌿) — ALL FOUR PASSAGES ARE FIXED, AND THIS PARAGRAPH IS NOW THE
STALE PROSE IT COMPLAINS ABOUT. READ THIS BEFORE THE CLAIM BELOW.** Left standing rather than
deleted because the lesson under it is right and worth keeping; but the claim itself would now send
a reader to correct code, which is the more expensive of the two errors this file ranks.

**Verified by CONTENT at sha `dc96a65b`, not by line number** — the coordinates below have all
moved:

| the claim | what the file says today |
|---|---|
| `memento_slot.py:33` justifies leg 2 by the shared pointer | it now opens *"THE REASON HAS CHANGED, so read this one rather than the story you may remember"* and keeps the leg on **a persona outliving its sessions** |
| `:47`'s LAYOUT table reads `slot=root POINTER .claude-memento.md` | the table reads `.claude-memento-<persona>.md`, and the line under it says the legacy shared name is **RETIRED** with **deliberately no fallback** |
| `reap_memento.py:49` argues from persona-lessness | it names `.claude-memento-<persona-slug>.md` and calls the shared name retired |
| `:134` likewise | it now carries *"THE RULING'S ORIGINAL PREMISE IS RETIRED AND ITS CONCLUSION IS NOT"* verbatim |

**Closed by two commits**, found with `git log -S` on the table's own text rather than by reading a
changelog: **`fdbc7938`** *"The premise retired, the leg did not"* (the LAYOUT table + the leg-2
justification) and **`0de35e20`** *"Three more passages arguing from a layout that is gone"*.
Positive control: `grep -n 'POINTER  \.claude-memento\.md' src/lupin_mcp/*.py` returns **nothing**,
and the same grep for the persona-scoped row returns the live table — so the search reaches.

⚠️ **AND NOTE WHICH DIRECTION THIS FAILED IN.** The paragraph below is not merely out of date — it
is an **instruction to go and fix four things that are already correct**. § *A WRONG COUNT PUBLISHES
A WRONG NUMBER; A WRONG MECHANISM SENDS THE NEXT READER AT INNOCENT CODE* ranks that as the dearer
error, and this is its purest form: the reader arrives, finds working code, and must then decide
whether the code is wrong or their reading is.

⚠️ **THE ONE THING I DID NOT DO**: I did not re-derive whether the *fixes themselves* are correct —
only that the four passages no longer say what this paragraph says they say. Whether the new prose
is right is a separate question and nobody asked it here.

🔴 **AND THE PROSE THAT ARGUES FROM THE OLD LAYOUT WAS NOT MOVED WITH THE CODE — FOUR PASSAGES, TWO
OF THEM IN THE FILE THAT WAS FIXED.** Standing at `73caf656`: `memento_slot.py:33` justifies leg 2
by the shared pointer, and `:47`'s LAYOUT table still reads `slot=root POINTER .claude-memento.md`
— **contradicting line 175 of its own file**, which now returns the per-persona name.
`reap_memento.py:49` and `:134` argue "never the root pointer" from persona-lessness, and that
module's docstring is what the paragraph above cites as the authority on which door owns which
slot. **A stale authority is worse than a stale note, because it is the thing other files point
at.**

⇒ **This is the same defect as the one that produced the fix, one level down.** The re-spin outage
came from a code READER of a moved name that nobody grepped for; these are PROSE readers of the same
name, in the same repo, including the file under the author's own cursor. **"Find every reader
before you move the writer" has to count the sentences that explain the code, not only the lines
that execute it** — those sentences are what the next person reasons from, and unlike code they fail
silently forever.

**A refusal here is legible — read it before theorising.** Given the wrong slot it names both
acceptable targets and the exact remedy command, and it recognises the one plausible wrong
destination (`~/.claude/mementos` at its bare top, which is neither slot nor a well-formed mirror —
a mirror lives at `<mirror_home>/<repo>/<record-path>`). If you are guessing which slot the verb
wanted, you did not read what it told you.

⇒ **Two records for one session is the NORMAL steady state**, not drift: a seat that may be either
reaped or self-respun legitimately has one in each slot. They are written by separate calls, so
they agree only where the writer put the same bytes in both — expect the self-respin nonce to
differ, and do not read that difference as corruption.


---

## 🔴 A WRONG INSTRUCTION GETS CAUGHT; A WRONG REASSURANCE DISARMS THE READER WHO WOULD HAVE CAUGHT IT


Found by **sam 🎙️** 2026-09-02, sweeping `workflow/memento-management.md` for passages still naming
the retired shared `.claude-memento.md` pointer as live. He was given the go on **seven** passages,
re-derived the line numbers rather than trusting his own earlier list, read each hit in context, and
came back with **eight** — three added, two withdrawn as legitimate records of a *rejected* proposal.
**His grep found the NAME; the classification needed the USE.** Landed at planning-is-prompting
`1c80e07`, whose own subject is the finding: *"the doc had two voices."*

**The part worth keeping is which passage turned out to be worst, because it was not on anyone's list.**

| passage | what it does | how it fails |
|---|---|---|
| **§ line 22** — *"`<project>/.claude-memento.md` for a self-`/clear`"* | an **instruction** to a dead path | the first person to follow it gets `self_respin` refusing with *"memento is stale"* — **loud, immediate, one reader** |
| **§3.2** — *"**A naive reader is already correct.** … an inherited "read `.claude-memento.md` and rehydrate" instruction … gets the **current record's full content**, with **zero extra action**"* | a **reassurance** that the dead path still resolves | **nothing fires.** It tells a reader who was about to check that checking is unnecessary — **silent, indefinite, every reader** |

⇒ **The reassurance sat directly above a banner announcing that same pointer was RETIRED.** Two
voices, adjacent lines, and **the stale half is the half that gives instructions** — which is why a
document can be *correct somewhere* and still be teaching the wrong thing.

🔴 **SO WHEN YOU RETIRE A NAME, SWEEP FOR TWO POPULATIONS, NOT ONE.** The instructions that USE it
are the obvious half and the cheap half. The sentences that **vouch for it** — *"this still works",
"you need not worry", "a naive reader is already correct", "either form is fine"* — are the ones that
cost you a reader's caution, and they rarely contain the imperative verbs a sweep greps for.

⚠️ **This is § *A HIT IS NOT A USE* pointed at prose instead of code**, and it lands harder here: a
wrong line of code fails when it runs, while a wrong sentence of reassurance fails by preventing the
run that would have exposed it. **Grade a doc's passages by what they DISARM, not only by what they
INSTRUCT.**


---

## 🔴 A ROW BODY IS A PLAN, AND A STALE MEASUREMENT IS MORE PERSUASIVE THAN A STALE OPINION


María 🌸's finding, 2026-09-02, and the largest of that evening. **A row body is written BEFORE
the work and is never revised as the work lands.** So a detailed body slowly becomes a to-do list
of finished things — and it reads as authoritative **because** it is detailed.

**The receipt is Rick's own P0, `8af64f5a`, which was wrong three times in ten minutes** and wrong
in the same direction every time: claiming as outstanding work that was already built. Its own
**"MEASURED GAP"** block is the worst of it — it states that `notifications.js` is **22,474 lines**
and **"calls NO transition endpoint."** Re-measured at `8319ead2`:

| the body's measured claim | what the file does |
|---|---|
| 22,474 lines | **23,781** |
| calls no transition endpoint | **POSTs `/api/tasks/{id}/transition` at line 10035** |

⇒ **Two managers independently concluded that P0 was untouched while it was substantially
complete.** Neither of us was careless: we read a block explicitly labelled as a measurement, with
a line count and a named absence in it, and a measurement is the thing you are supposed to be able
to trust.

🔴 **THAT IS THE MECHANISM, AND IT IS WHY THIS IS WORSE THAN ORDINARY STALENESS.** A stale
*opinion* announces itself as a judgement and invites a second look. A stale *measurement* carries
a number, a file and a line, and every reader treats those as checkable facts rather than as claims
needing a date. **The precision is what disarms you** — the same defect as § *A WRONG INSTRUCTION
GETS CAUGHT; A WRONG REASSURANCE DISARMS THE READER*, one level up: there a sentence vouches for a
dead path, here a figure vouches for a dead reading.

⇒ **Two obligations, and neither is "keep the body up to date" — that is a habit, and a habit is
not a control:**

1. **STAMP EVERY FIGURE IN A ROW BODY WITH THE SHA AND THE MOMENT IT WAS TAKEN.** *"22,474 lines @
   `8bf71a64`, 2026-08-31"* is still true a week later; a bare `22,474` becomes false without ever
   changing. This is § *A COORDINATE IS NOT A REFERENCE* applied to your own numbers.
2. **RE-MEASURE BEFORE YOU ACT ON A BODY'S MEASUREMENT — never before you merely read it.** The
   check is cheap (`wc -l`, one `grep`) and it is the only thing standing between a detailed plan
   and a manager's evening.

⚠️ **AND READ A ROW BODY FOR WHAT IT IS: THE PLAN AS OF ITS WRITING, NOT A STATUS.** The status
lives in the transitions and the receipts. A body that reads like a status is the most convincing
wrong answer on the board, because nothing about it looks stale.


---

## Off-peak scheduling — the boot-window measurements

> Moved verbatim from `CLAUDE.md` 2026-09-08 (sha `ed653c8b`, row `f1400995`).
> The operative rule stayed inline; this is the receipt.

### Off-peak scheduling rule (operational)

Max-plan usage has rolling-window limits. Batch bounded jobs running during Rick's interactive peak window can throttle his real Claude Code work.

⚠️ **CORRECTED 2026-08-17 (Rick's ruling, row `f0b3f630`). The old window pointed at hours the box is powered OFF.** It read "Optimal: 12 AM – 9 AM EDT (Rick asleep, zero interactive use)" — true about Rick, false about the machine. Measured boot history, unbroken since Aug 5: the host is **DOWN ~10:53 PM – 7:17 AM**. Every seat that followed the rule correctly still had its job sit dead until the next boot and drain hours late — two jobs scheduled for 00:30 and 01:15 ran at ~10:07 the next morning.

⚠️ **CORRECTED AGAIN 2026-08-20 (Rick's ruling). The 08-17 correction replaced hours the box was OFF with hours it is usually NOT UP YET — same failure, one step smaller.** It named **7:30 AM** as the start, derived from a single boot at 07:17 on Aug 6. **Measured across the 12 morning boots since Aug 4** — `08:52 · 09:27 · 07:17 · 09:14 · 09:52 · 09:56 · 09:20 · 10:52 · 09:48 · 09:03 · 09:17 · 09:43` — the **median is 09:24 and eleven of twelve are after 08:52**. A job placed at 7:30 sits dead ~1.5–2.5h on almost every day.

✅ **RE-CONFIRMED 2026-09-02 (Mr. Radio 🦉, row `10b1cbe5`) ON A SAMPLE 5.7× LARGER, FROM A DIFFERENT INSTRUMENT — THE WINDOW HOLDS AND IS NO LONGER RESTING ON SIXTEEN DAYS.** `journalctl --list-boots` gives **91 morning boots spanning 2026-04-14 → 09-02**: **median 09:34**, earliest 07:17, latest 12:54, **80 of 91 after 09:00**. Against the 16-boot sample below (median 09:45) the two agree to eleven minutes across four and a half months, so the fourth measurement of this rule is the second that did not move it.

⚠️ **AND IT ADDS ONE FIGURE THE SMALL SAMPLE COULD NOT SEE: only 26 of 91 boots are after 10:00.** So the box is usually up BEFORE the optimal window opens — 10 AM is conservative, which is the safe direction, and there is no case for moving it earlier off this data.

⚠️ **THE MID-DAY RESTART IS NOT AN ANECDOTE EITHER: 18 boots in the 109 are after 13:00**, spread across every month. "Optimal" still means *most likely up*, never *guaranteed up* — a long job must tolerate a restart.

🔨 **RICK RULED 2026-08-31 ~20:08 EDT, by voice: the boot window is a REAL CONSTRAINT, not a record of his habit.** Schedule batch work around it. That ruling settled a question open since 08-20 (row `10b1cbe5`); this stamp exists so the next reader knows the figures were re-checked rather than inherited.

⚠️ **RE-MEASURED 2026-08-30 (Krishna 🦚, row 9078a035 · commit 2df3aefb). THE WINDOW HOLDS; THE FIGURES BELOW ARE NOW OPTIMISTIC — AND THIS IS AN UPDATE, NOT A CONTRADICTION.** Taking `last -x reboot | head -20` afresh gives **16 morning boots** spanning Aug 10–30: `09:27 · 10:15 · 09:35 · 09:27 · 11:58 · 11:01 · 09:53 · 09:19 · 09:43 · 09:17 · 09:03 · 09:48 · 10:52 · 09:20 · 09:56 · 09:52` — **median 09:45, earliest 09:03, latest 11:58**, shutdowns clustering 22:26–00:20.

**The two samples RECONCILE rather than disagree**, which is the only reason to trust either: the 08-20 list starts Aug 4 and includes the 07:17 outlier from Aug 6 that sits outside this window; this list adds six newer days and no boot in it is before 09:03. **The distribution moved later — median 09:24 → 09:45 — so 10 AM – 1 PM is more right than when it was written, not less.** What is now stale is the **9 AM** boundary in the DEAD row and the "well past 8:52 AM" phrasing: on this sample the box is usually still down at 9:30, and on two of sixteen days past 11:00. Read the dead window as ending at **10 AM**.

⇒ **This is the third measurement of the same rule and the first one that did not move the recommendation.** That is what a stabilising figure looks like — but it is still 16 samples, so re-derive rather than quote this paragraph too.

🔴 **DO NOT TRUST THIS TABLE EITHER — RE-DERIVE IT.** This rule has now been wrong twice, both times because someone generalised from too few boots. **Measure before you schedule:**

```bash
journalctl --list-boots --no-pager | tail -30   # the DURABLE instrument — read it yourself
last -x reboot | head -20                       # ⚠️ SHORT MEMORY — see the warning below
```

🔴 **`last -x reboot` IS THE COMMAND THIS RULE HAS ALWAYS PRESCRIBED, AND ON 2026-09-02 IT
RETURNED EXACTLY ONE BOOT.** `wtmp` had rotated the previous day, so `last` reported
`wtmp begins Tue Sep 1` and a single line. Nothing about that output says it is a
one-day window — it is a correct answer to a question about a file, read as an answer
about a machine. A reader following this section's own instruction on that morning would
have re-derived the window from **n=1**.

⇒ **`journalctl --list-boots` is the durable instrument** and is what the figures below now
come from: 109 boots reaching back to April against `wtmp`'s one day. The rotated file is
still readable (`last -x -f /var/log/wtmp.1 reboot`) but you have to know to ask, which is
the same trap one level down.

⇒ **This is this file's own "name the population" rule firing on this file's own remedy.**
An empty-or-tiny result and a real one print in the same format, and the only defence is
to state the sample size beside the median — which is why every figure in this section
carries its `n`.

**The constraint is the box, not just Rick's sleep:**

| Window (EDT) | Verdict | Why |
|---|---|---|
| ~11 PM – 10 AM | ☠️ **DEAD — never schedule here** | Host is usually powered off, and on most days is still down past 09:30 (16 boots to Aug 30: median 09:45, earliest 09:03, two past 11:00). A job here does not run late — it does not run at all until boot. |
| 9 PM – 11 PM | ❌ Peak — avoid | Rick's interactive window; competes with his real work. |
| **10 AM – 1 PM** | ✅ **OPTIMAL — schedule batch work here** | Comfortably after the median boot (09:24 on the Aug-4 sample, 09:45 on the Aug-30 one — it moved later, so this window got safer). Rick is barely on. The only window reliably both up and quiet. |
| 1 PM – 9 PM | 🟡 Acceptable | Box up, some interactive use, well below peak. |

**Rule**: any non-interactive bounded job (batch generation, scheduled regression sweeps, podcast/presentation/research) MUST set `scheduled_at` inside a window the box is UP for — **prefer 10 AM – 1 PM EDT** — via `/api/v2/submit` (field defined on `SubmitRequest` at `src/cosa/rest/routers/v2_ask.py`). User-clicked synchronous bounded jobs are exempt.

⚠️ **CHANGED 2026-08-21.** This line used to name `/api/claude-code/submit`. That door and its `/api/claude-code/queue/submit` alias are now tombstones answering **410 Gone** (Rick's ruling: the Claude Code job is *upgraded* to the v2 front door, not left to die on the vine). The work enters through `/api/v2/submit` naming the command `agent router go to claude code`; `scheduled_at` stays TOP-LEVEL because it tells the queue *when* to run, and `args` is checked against the command's own argument contract, which no scheduling instruction is in.

⚠️ **And the box goes down mid-day too.** On 2026-08-20 it was down **14:34–18:07**. "Optimal" means *most likely up*, never *guaranteed up* — a long job should still tolerate a restart.

**If a job does land in the dead window**, the catch-up is no longer silent: `job_persistence.py` emits a `[CJ-CATCHUP-LATE]` line naming `scheduled_at` vs actual and hours-late (`fef78ce3`, with a negative control at `f0b7c589` proving it stays quiet on every non-catch-up path). A late drain is now visible rather than reported as a normal run — but visible-and-late is still late.

Example:
```json
POST /api/v2/submit
{
  "command"      : "agent router go to claude code",
  "args"         : { "prompt": "…", "task_type": "BOUNDED" },
  "scheduled_at" : "2026-08-22T11:00:00-04:00"
}
```

(This example used to read `02:30` — inside the dead window. A copied example is how a bad window propagates faster than the prose that describes it.)

**Mandate for new design**: any proposal for a new LLM-driven feature MUST first answer "can this be a bounded CC job?" and document the answer. If "no", document which guardrail it hits.


---

## PR merge requirements — the tier-count measurements and the stdout-watcher analysis

> Moved verbatim from `CLAUDE.md` 2026-09-08 (sha `ed653c8b`, row `f1400995`).
> The operative rule stayed inline; this is the receipt.

## PR MERGE REQUIREMENTS

<!-- merge-pyramid-suites: unit cosa coverage typescript smoke websocket e2e integration -->
**All must pass before merging to main** (venues + commands per §TESTING above), run in this order: unit (:7999) → **cosa (:7999 — in-tree `src/cosa/tests/**`, `src/tests/run-cosa-tests.sh`; joined the pyramid 2026-08-13, row d83d025b)** → **coverage (:7999 — `src/tests/run-coverage-gate.sh`; joined the pyramid 2026-08-29, row e2099400). It does NOT re-run anything: the unit and cosa tiers above append to one isolated data file and this step renders it, checks pyproject's `fail_under`, and checks that the FRAME still measures every file it claims. Before it existed, NOTHING in the build asked for coverage — no addopts, no runner, no injection in `job.py` — so `fail_under` fired only when a human typed `--cov` by hand, and the 100% mandate had teeth on the TypeScript side only.** → **typescript (:8000 scheduled — `src/tests/run-typescript-tests.sh`, c8 at 100%, ~8-25 min so it fails the :7999 two-minute rubric; runs inside the capped `jstest.slice` cgroup — ban lifted 2026-08-25, row 92e94cb7)** → smoke (:7999) → **serial bridge guard (`src/scripts/run-serial-bridge-guard.sh` — read the note below before reading its verdict)** → WebSocket smoke (:7999) → E2E UI + visual regression (:8000 scheduled) → **integration (:8000 scheduled — FINAL GATE)**. Each requires 100% pass. Wait for E2E to complete before launching the integration gate; PID-file guards block concurrent runs.

The **cosa tier's count was being asserted without ever being run.** Now measured **three times across two different trees**:

```
@cba072f8  8788 passed, 26 skipped  in 254.27s   EXIT=0   (Cheech, 2026-09-04 19:37 EDT)
@3a8ce109  8668 passed, 26 skipped  in 280.72s   EXIT=0   (Tiberius, 21:16)
@17e78c98  8668 passed, 26 skipped  in 274.45s   EXIT=0   (Rio)
@17e78c98  8668 passed, 26 skipped  in 274.53s   EXIT=0   (Rio)
@b3c76d55  8671 passed, 26 skipped  in 275.56s   EXIT=0   (Tiberius, tier-wide thread probe)
@b3c76d55  8671 passed, 26 skipped  in 276.67s   EXIT=0   (Rio, independent)
```

⚠️ **THE 08-30 FIGURES ARE NOT WRONG, THEY HAVE DRIFTED — 8668/8671 → 8788 (Cheech 🌿, sha
`cba072f8`, 2026-09-04 19:37–19:41 EDT, `LUPIN_UNIT_NETWORK=block`, outbound connections 0, EXIT 0,
ZERO failures).** Tests were ADDED in the five days between; nothing regressed, and the +120 is
drift of the same kind this section already documents at +3 and +46. **This row is here because
that is what the section's own instruction returns when you follow it** — re-derive rather than
quote — **and because a five-day-old count quoted on sight is how `8,622` stood from 08-22.** It
will be stale again; re-derive rather than quote this one too.

**FIVE runs, two seats, three shas — and the two different counts RECONCILE rather than conflict.** `git diff 17e78c98..b3c76d55 -- src/cosa/tests` is **+4 `def test_`, −1 removed = +3**, which is exactly `8668 → 8671`. Verified independently by both of us. A count that moves *and* whose movement is fully explained by the diff is stronger evidence than a count that merely repeats.

The figure in circulation was **8,622/0**, which is simply the count as of **08-22**. Nothing regressed — **zero failures** in both runs — and 7 commits touched `src/cosa/tests` in between, adding a net **+44** `def test_` (`402e528c` `f2be1f6d` `8cb320bb` `0dd919d2` `927076a4` `566cb971` `e38abe43`) against a measured +46; the remainder is parametrization. **Stale expectation, not regression**, proven both ways rather than inferred from the unit tier's similar drift.

**Three samples across two shas, by two seats**, so 8,668 is neither a one-tree artifact nor a one-runner one; wall time is tight too — 274.45 / 274.53 / 280.72s. ⚠️ **What these samples are NOT independent of: the HARNESS** — wider than box-and-interpreter (Rio's correction to my wording). All three share the same `.venv` package set, the same `conftest`, the same runner script, the same env (`LUPIN_UNIT_NETWORK=block`, `LUPIN_ROOT`, `PYTHONPATH`), and the same OS and clock; **Rio's two additionally shared the same uncommitted working tree**, so they are not even tree-independent of each other in the untracked sense. Any one of those could agree wrongly: a defect living in the harness rather than the tree reproduces identically across all three and reads as agreement. ⚠️ **It moved within the same evening** — **8,671**, three more than 8,668, with no failure anywhere. The cause is named rather than guessed: three commits landed cosa tests in that window (`6874aec8`, `b92f663c`, `402e528c`), and the commit carrying this note touches `CLAUDE.md` only. Re-derive rather than quote on sight; that habit is what let `8,622` stand since 08-22, and the number is demonstrably a moving target even across one night — but the number itself now rests on more than one run.

**The stdout-watcher hazard cannot reach this tier, and the durable reason is the ABSENT THREAD, not a count.** Nothing in the cosa tier imports `lupin_mcp.cosa_voice_mcp`, so the daemon watcher never starts in that process and there is no polluting writer at all. Measured, not grepped, and over the WHOLE tier rather than a subdirectory (Rio's correction — my first probe covered only `unit/rest/`, 2,673 tests, which cannot speak for a tier-wide claim): a thread probe at `pytest_sessionfinish` across all of `src/cosa/tests/` — **8,671 passed** — reports `WATCHER_PRESENT: False` — **and Rio's independent run at the same sha reports the same**, so the absence is not one seat's artifact. ⚠️ **The absence is SPECIFIC to the watcher, not a claim that the tier starts no threads**: the same probe reports `['GhostJobSweeper', 'GhostJobSweeper', 'MainThread', 'io-embed_0', 'io-embed_1']`. Cosa runs daemon threads; none of them is the one that writes session events to stdout. (Every textual `cosa_voice_mcp` hit in `src/cosa/` is a path string, a path-suffix assertion, or a comment — no import.) **Corroboration, NOT the proof**: Rio's census finds 379 stdout-capturing test functions across 89 files with **zero** parsing the capture as JSON. That number is a census of today's tree and one new test moves it (Rio's correction); the missing importer is what holds. The unit tier is the exposed one — 15 files parse stdout as JSON there; see `src/rnd/v0.2.0/2026.08.24-import-time-watcher-thread-poisons-stdout-tests.md`.

The **serial bridge guard** step is the tier-2 whole-directory contact check (row e2ae4102) that the concurrent unit run deselects (`-m "not serial_bridge_guard"`) because a live peer's bridge write would false-accuse it. If it reports contact, a hook may be resolving its directory from a hardcoded real path instead of the seam. Dropping this line silently removes the guard — the concurrent scoped canary does not see a merge into a live seat.

> 🔴 **DO NOT WAIT FOR A "QUIESCENT BOX" — THERE IS NO SUCH STATE** (row `5a68c92c`). This line used to say "on a quiescent box", and the row-level guidance said "run it when you are the only session writing bridges." **That condition cannot be satisfied and asking peers to pause will not create it.** Measured 2026-08-24 with no suite running anywhere: **13 entries under `~/.claude/sessions` changed in 60 seconds**, and four live seats wrote bridges inside ten minutes — **including the seat running the guard**, which writes its own bridge and its own listener files while the guard executes. The precondition named a state that never exists, so a red told the reader nothing and the sanctioned response ("re-run") was indistinguishable from weakening a gate.
>
> **How to read a red instead — real contact is DETERMINISTIC, peer noise is NOT:**
> 1. **Re-run and compare the NAMED file.** The same filename every run = contact. A different file each run, or none, = peer noise. ⚠️ **This cuts both ways: one GREEN is also one sample.** The discriminator is determinism, not the colour of the result — on a check whose failure mode is nondeterministic, a single pass is as weak as a single fail. Run it more than once before reporting either.
> 2. **Identify the writer.** Read the named file's `session_id` / `cc_pid` and check whether it belongs to a live seat that is not the test: `ls /proc/<cc_pid>` — if that seat is alive and is not you, it is noise, not contact.
>
> ⚠️ **Scope note, pending a decision (do NOT "fix" this by narrowing the glob).** `fingerprint_dir` globs `*` rather than `cc-*.json` **deliberately** — row `877794ed` widened it because the narrow form MISSED real `cc-listener-*.stderr` and `.spawn-lock` writes. The cost of that correct decision, measured: the guard sha256s **6,498 entries / 154 MB twice per test**, of which **5 are Lupin bridges**; the exclusion list carries **2 names against ~4,676 `.log`/`.stderr` files**. Narrowing the glob re-opens the hazard `877794ed` found, so the scoping question is Rick's, not a drive-by. Analysis: `src/rnd/v0.2.0/2026.08.24-serial-bridge-guard-unsatisfiable-precondition.md`.

Integration is the final gate because it exercises complete user workflows across API + DB + auth on a real server — catching regressions unit tests miss.

**On failure**: do NOT merge. Fix the failing tests first, then re-run the full suite. A genuinely-flaky-not-your-code failure gets documented + a separate fix — never a merge bypass.

**Testing anti-patterns** (NEVER):
- `curl` for pipeline/integration testing, or manual `/api/push` + poll `/api/get-queue/done` — use the automated scripts (`LivePipelineTestBase`), never bespoke curl.
- Running :8000-bucket suites (integration, E2E UI, proxy-integration, presentation regression) against :7999 — they depend on server monopoly; the dev server is not a stand-in.
- Side-door injecting :8000 tests via curl / direct `/api/push` / in-process instantiation / anything but `POST /api/test-suite/submit` — collides with in-flight runs and poisons both. (Submission itself is self-authorized on a verified-idle server; the prohibition is on the side-door, not on submitting.)
- Curl is acceptable ONLY for: API-reference docs, deployment health checks, one-off debugging (never committed).
- New agent? Add an automated smoke test (see `.claude/skills/agentic-voice-workflow/SKILL.md`).

### Required Environment Variables

```bash
export LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL="your@email.com"
export LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD="yourpassword"
```

> **Session 267 unification**: All smoke tests, proxy tests, and pipeline tests now use the
> `LUPIN_TEST_INTERACTIVE_MOCK_JOBS_*` prefix. This ensures test and proxy authenticate as the
> same user (same WebSocket channel), preventing "Operation cancelled" failures.

### Usage Pattern (Python)

```python
import os

email    = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL" )
password = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD" )

if not email or not password:
    raise ValueError( "Set LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL and LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD environment variables" )
```

### When to Use

- Any smoke test that calls authenticated API endpoints
- Integration tests that require login
- Manual testing scripts
- Protocol verification tests that need real user context

**Reference**: See `src/tests/AUTH-TESTING-GUIDE.md` for credential patterns. For pipeline testing, always use automated smoke tests — never manual curl.


---

## The :8000 idleness verification — the monopolize_id caller audit

> Moved verbatim from `CLAUDE.md` 2026-09-08 (sha `ed653c8b`, row `f1400995`).
> The operative rule stayed inline; this is the receipt.

### :8000 (test) — monopolize mode, scheduled only

Submit via `POST /api/test-suite/submit`. **Self-authorization rule (2026-06-06): a verified-IDLE `:8000` — nothing running, nothing scheduled — is bounce-then-schedule SELF-AUTHORIZED; the user is NOT a gate.** Only **killing a LIVE in-flight job** needs the user's word. **Never** inject via ad-hoc curl, direct queue push, or in-process server instantiation — side-door injection collides with in-flight scheduled runs and poisons both.

🔴 **HOW YOU VERIFY IDLE — one command, and its exit code (row `e6b8fe56`, 2026-08-25).** This rule already said to read the queue, and a seat that followed it was never reading `monopolize_id` — **the rule itself was not the defect** (Tiberius's caller audit, `7f935140`, `src/rnd/v0.2.0/2026.08.24-monopolize-as-idleness-caller-audit.md`). What was missing is a single reliable way to do what it asks. `pool-status` cannot be that way: **measured** against real queues, `monopolize_id` moves for exactly ONE condition — a monopolize-flagged job that has already **started** — so it answers *which job holds the slot*, an identity question, and says nothing about work that is QUEUED, running INLINE on the consumer thread (row `99b09840`), or in the shared pool. **And the queue listings cannot do it alone either**: `/api/get-queue/{q}` is **user-filtered** and the gate account is not an admin — `?user_filter=*` answers **403**, so a peer's queued job is not in your listing at all.

```bash
PYTHONPATH=src python3 -m cosa.rest.venue_idle --port 8000 ; echo "exit=$?"
```

**The exit code is the answer: `0` IDLE · `1` BUSY · `2` UNKNOWN.** It reads the unfiltered, unauthenticated `GET /api/busy` — run depth, **todo depth**, shared-pool inflight, monopolize slot — and every lane must be empty. 🔴 **UNKNOWN IS NOT IDLE.** UNKNOWN with only `todo_queue_size` missing means that container predates this row and cannot see waiting work; the remedy is a **bounce** (a code pickup), not a `--force-recreate`. Treating a signal's absence as proof of absence is the defect itself.

**Placement, once you have a `0`:** empty queue → bounce (to clear static-snapshot drift, see §reference) + schedule + run now; something already SCHEDULED (queued, not yet running) → still self-authorized, but set `scheduled_at` AFTER the queued job (never jump an expected-next run); something RUNNING → queue behind it, no bounce.

Eligible if **any**:
- Mutates persistent state (DB rows, shared files, LLM API spend, enqueues jobs).
- Runtime > 2 minutes.
- Needs server monopoly (E2E UI, integration, regression sweeps).

Suites that qualify:
- `src/tests/smoke/test_proxy_integration.py` (any scenario — CRUD + expediter mutate state)
- `src/tests/run-integration-tests.sh` (final merge gate)
- `src/scripts/run-e2e-ui-tests.sh` (functional + visual)
- `src/tests/run-presentation-regression.sh` (all variants)

The AI **self-authorizes** :8000 runs on a verified-idle server (logged, no human gate) and owns both scheduling and executing. The ONLY user-gate is **killing a live in-flight job**. Never budget approval, never tester-duty deferral, never an idle-slot ask.
