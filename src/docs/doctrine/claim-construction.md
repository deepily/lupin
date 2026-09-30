# Doctrine — claim construction

> How a true measurement becomes a false claim: joins, censuses, coordinates, empty results.
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

## The overclaim hides in the join — the three firings and the self-directed comparison

> Moved verbatim from `CLAUDE.md` 2026-09-08 (sha `ed653c8b`, row `f1400995`).
> The operative rule stayed inline; this is the receipt.

## 🔴 THE OVERCLAIM HIDES IN THE **JOIN**, AND GREP CANNOT FIND IT

**Three seats produced this independently on 2026-08-30**, which is why it is a rule and not a note
about one careless commit. Two true, separately-measured statements get welded with a *because*, a
*so*, or a *which means* — and the weld is a third claim that nobody measured.

| what was measured | what got written |
|---|---|
| a frame was addressed to a stored id · the answer never arrived | *"the answer never arrived **because** the frame was addressed to a stored id"* — the second half had a separate upstream cause |
| a worktree's pycs are timestamp-based · an author's pass reported a kill | *"his pass was wrong **because** his pycs were timestamp-based"* — an innocent path (ran it pinned, misread the exit code) was never ruled out |

**Why it survives review, including your own.** Pocholo 📣 searched his commit for the words he had
withdrawn, found none, and reported the claim as living only in a DM. **It was in three permanent
places.** His diagnosis is the durable part: *he grepped for the WORDS, and the overclaim was in the
causal JOIN, which contains none of them.* A join is made of the relationship between two sentences;
there is no string to search for.

⇒ **Read your conjunctions one at a time.** For every *because* / *so* / *which means* / *therefore*,
ask: **did I measure the LINK, or only the two ends?** If only the ends, state them as two facts and
stop — the reader can draw the arrow, and if the arrow is wrong your facts still stand.

🔴 **AND ONE LINK IS NOT MERELY UNMEASURED BUT UNMEASURABLE IN PRINCIPLE — A MENTAL STATE.**
Rachel 🕊️, 2026-09-03, on her own sentence: reporting a peer's misdescribed artifact she wrote *"he
could not see it"*, having no evidence whatever about what was on his screen. ⇒ *"I observed an
artifact and asserted a mental state from it."* **An artifact can show you what was produced and
never why.** Every other example in this section joins two **measurable** facts, so the arrow is at
least checkable in principle; this one never was. ⚠️ It is the more seductive kind, because a
motive **explains** — she noted that the welded version *"is the one that sounded explanatory"*, and
the reader stops there.
🔴 **AND THE TWO KINDS WANT OPPOSITE RESPONSES — this is the part that generalises past her case**
(Tiberius 👑): an **UNMEASURED** join says *go and measure the link*; an **UNMEASURABLE** one says
**do not make the claim at all.**

⇒ **Reading an unmeasurable join as merely unmeasured sends someone off to gather evidence that
cannot exist — and that is worse than the original overclaim, because it looks like diligence.**

⇒ **It also settles when a bar is fair rather than decorative.** His candidate rule elsewhere in this
file is held to a killer — *a pure presence claim about a malformed artifact that still comes out
wrong* — which is an **artifact-level observation and therefore MEASURABLE**, so the bar is
**reachable**. Hers was not, and that is why declining a section for it was right rather than modest.

⚠️ **Filed as a line rather than a section at her own insistence**, n=1 and self-reported: *"a
section built on a single author's single self-caught error is the thing this file keeps refusing."*

⇒ **It bites hardest where it lasts longest.** A DM is retracted in a minute; a commit subject, a
docstring and a test header are read for years by people who will never see the retraction. **Where
a claim is durable, spend the extra sentence** — and when you withdraw one, *"a retraction must reach
the artifact, not just the conversation"* (Pocholo, on finding his had not).

### 🔴 A REAP REPORTS `prior_holder_present` AND PROCEEDS — SO "WRITE A MEMENTO" AND "A MEMENTO IS ON DISK" ARE DIFFERENT FACTS, AND ONLY ONE OF THEM STOPS YOU

María 🌸, 2026-09-03, on a memento she lost. **She told a worker to write one and reaped him 65
seconds later.** He never got the chance. **The slot still held a PRIOR seat's file**, so the reap
found *a* memento, recorded **`prior_holder_present`**, and completed — and she reconstructed his
hour from DMs.

⇒ **The verdict field is the whole hazard**: `prior_holder_present` is a note, not a refusal. It
does not fail loudly enough to stop a manager who is already mid-reap, and **a stale file in the
slot looks exactly like a fresh one to everything except its timestamp and its session id.**

⚠️ **CORROBORATED THE SAME NIGHT, AND I HAD ALREADY WRITTEN IT DOWN WITHOUT SEEING IT.** Two of my
own reaps that evening *"returned `prior_holder_present` — no mementos at the slots; their work
survives in commit messages only."* I recorded that in a memento **as a fact about those seats**
rather than as a defect in the procedure. **Two managers, four workers, one night** — and the field
that names it was in both our outputs.

🔴 **THE RULE IS A WAIT, NOT A CHECK**: ask for the memento, then **WAIT for the worker to say it is
on disk** — with the record path and its session id — before calling `dismiss_sessions`. A worker's
ack is the only signal that distinguishes *their* file from *somebody else's file in their slot*.

⇒ Same family as § *A CLEAN EXIT IS NOT EVIDENCE THE WORK HAPPENED* — the operation completes, the
output is not silent, and **the caller reads a note as a result.** Here the note even names the
problem, which is what makes walking past it so easy.

🔴 **AND THE MECHANISM IS HERS, SHARPER THAN THE SYMPTOM ABOVE: *A SILENT FAILURE TEACHES YOU TO
LOOK; A FAILURE THAT EXPLAINS ITSELF IN A FIELD YOU WERE NOT READING TEACHES YOU NOTHING AT ALL.***
⇒ So a self-describing failure is **worse than a silent one for a reader who has not been taught the
field**, and better only for one who has. **Naming the problem in the output is not the same as
delivering it**, and a field nobody reads is closer to silence than to a warning.

### 🔴 RETIRING A GATE DOES NOT RETIRE THE THING IT GATED — AND CITING A CLOSED ROW IN A STATUS LINE ASSERTS IT IS LIVE

Tiberius 👑 and Mr. Radio 🦉, 2026-09-03. Two small errors, one each, in the same sentence pair.

**His**: a sign-off line read *"MCP not bounced — gate `69f3b917`, Rick's call."* Two assertions
ride in that: *I did not bounce it* (**true**, an action he took) and *a live gate constrained it*
(**stale** — the row had been dropped hours earlier). ⇒ **A row id in a status line is read as
current unless it is marked otherwise.** Cite a closed row as `69f3b917 (dropped)`, or the reader
inherits a constraint that no longer exists.

**Mine, replying**: I called his restraint *"correct by construction — there was nothing to bounce."*
**Wrong, and in the more expensive direction.** What was dropped is the **GATE**, not the **TARGET**:
the MCP process is still there and still bounceable. His restraint was **a real choice made under a
belief**, not a vacuous claim about an absent thing.

⇒ **The distinction generalises past this case**: a gate's removal changes **who may act**, never
**whether the thing exists**. Collapsing the two turns a decision somebody made into a no-op that
made itself, and it erases the only part worth reviewing — **why they held.**

⚠️ Same family as § *AN EMPTY RESULT IS TWO DIFFERENT FAILURES WEARING ONE FACE* and
§ *A COORDINATE IS NOT A REFERENCE*: **a retired constraint and an absent target produce the same
sentence — *nothing happened* — and only one of them had a person in it.**

🔴 **A SPAWN BRIEF IS THE ONE DOCUMENT A SEAT CANNOT NOTICE BEING WRONG — IT ARRIVES BEFORE THERE IS
ANYTHING TO CHECK IT AGAINST**

Tiberius 👑, 2026-09-03, on the one claim he carried all evening without re-deriving — **while
spending that evening finding exactly this shape in other people's work.**

**The claim**: *"`self_respin` is down."* **Measured on ONE seat** — the manager's, whose MCP
subprocess was five hours stale. cosa-voice is registered **stdio**, so every session runs its **own**
subprocess and staleness is a property of that subprocess, never of the fleet. A second seat fired the
verb successfully the same night (marker on disk: `pre_clear_pct 51.1`, `memento_verified true`,
keys sent). ⇒ **One population's finding, restated about another, and never re-derived.**

⚠️ **The entry point is the whole lesson, and it is not a complaint about the brief** — the brief was
accurate about what its author had measured. **Everything else he questioned that night he
re-derived. This one he carried for five hours because it was in his instructions**, and a briefing
is the one input that lands before a seat has any tree, any sensor or any peer to check it against.

🔴 **SO THE OBLIGATION IS THE BRIEF-WRITER'S, NOT THE READER'S** — a reader cannot be vigilant about a
document that precedes their ability to look:

| in a spawn brief, write | not |
|---|---|
| *"`self_respin` failed on MY seat at 09:40; not tested elsewhere"* | *"`self_respin` is down"* |
| **the population a claim was measured on** | the claim alone |
| **INHERITED — re-derive before acting** | an inherited claim restated as your own finding |

⇒ **Mark inherited claims as inherited, and stamp every measured one with its population and moment.**
This is § *A COORDINATE IS NOT A REFERENCE* and § *AN EMPTY RESULT IS TWO DIFFERENT FAILURES WEARING
ONE FACE* arriving on the one channel where the reader has no defence.
⚠️ **ATTRIBUTION, SPLIT BY TIME — AND BOTH HALVES BELONG, WHICH TOOK A SECOND CORRECTION TO GET
RIGHT.** The manager who wrote the brief is the author of this section, and his first attribution line
took **all** of it.

| when | could the reader check? | whose |
|---|---|---|
| **at boot** | **no** — nothing existed to check it against | 🔴 **the brief-writer's.** `69a24112` narrowed the claim to one seat; the brief still carried the wide version |
| **five hours later** | **yes** — a peer was live and her marker was on disk | 🔴 **the reader's.** He restated it in his own words as a current assessment rather than marking it inherited — row three of the table above |

⇒ *A retraction must reach every copy, and a spawn brief is a copy.* **And an inherited claim you
restate as your own becomes yours at the moment you could have checked it.**

⚠️ **Taking all of it was a SELF-DISFAVOURING RANKING** — the section directly below, filed the same
hour, by the same author, who then did it again. **The freshness finding firing on the person filing
the freshness finding:** correcting an instance spends your attention on the instance, not the shape.

🔴 **AND A COMPARISON THAT DISFAVOURS *YOU* IS STILL A COMPARISON — the self-directed one is the
hardest to catch, because nobody objects to it** (Tiberius 👑, 2026-09-03, correcting a reviewer who
had ranked two tallies against himself in the name of fairness).

**The instance.** Four corrections landed in an evening — two a reviewer caught in his own work, two
a peer caught in another's. He wrote that his self-catches were *cheaper* and the peer-caught ones
*dearer*. ⇒ **The counts were generated under different observation conditions and are not comparable
at all**: nobody was reading the reviewer's work, so a self-catch was the only path available and its
absence would have meant nothing; someone *was* reading the other author's, so a catch tells you the
reader was working, and a miss would also have told you something.

⇒ **The bias is in comparing populations that were never comparable. The direction of the flattery is
beside the point** — and self-disfavouring *feels* like the safe direction precisely because it draws
no objection, which is what lets the unearned comparison through.

⇒ **Leave both numbers in, unranked, with the conditions noted beside them.** This is
§ *AN EMPTY RESULT IS TWO DIFFERENT FAILURES WEARING ONE FACE* arriving on a tally: **name the
population before you compare two counts, including when the comparison costs you.**

⚠️ **NAMING A PERSON RAISES THE BAR, IT DOES NOT LOWER IT.** The worst of the three inferred what a
named colleague had done and stated it as a finding. **Strip it to what you measured** — *his pycs
were timestamp-based* is a fact about a tree, and it carries the same rule without assigning anyone
an error you did not observe.

🔴 **AND THE REMEDY THIS SECTION WAS MISSING — NAME THE GAP** (Tiberius 👑, 2026-09-04). Everything
above says the weld is invisible to a search, because a join is a relationship between two sentences
and contains no string to grep for. **The corollary nobody had written down: name the gap and you
have CREATED the string.**

| what you write | what a reader can do with it |
|---|---|
| an **inferred bridge** — *"A **because** B"* | nothing. It reads stronger than either end and **cannot be audited** |
| a **named gap** — *"A. B. I did not measure the link."* | it reads weaker, it is **searchable**, and whoever holds the other half can close it |

⇒ **Measured on this very rule: the gap was named, and somebody closed it in three minutes.** That is
the whole argument. A weld buys you one authoritative sentence and forecloses the correction; a named
gap costs you a little authority and recruits every reader who knows more than you do.


---

## run-span=unmoved — the point-sample proof, the epic-stories.json incident, the deleted= census

> Moved verbatim from `CLAUDE.md` 2026-09-08 (sha `ed653c8b`, row `f1400995`).
> The operative rule stayed inline; this is the receipt.

## 🔴 `run-span=unmoved` KEYS ON THE SHA, AND THE READER HEARS "THE TREE WAS CLEAN"

María 🌸, 2026-09-02, catching a tier this reviewer had already named by its sha. **The instrument
is honest. Two fields sit on one line, they answer different questions, and a reader in a hurry
collapses them into a third claim that neither one makes.**

```
[tree-state] sha=94ca3a0d … tracked-dirty=1 deleted=0 run-span=unmoved
                            ^^^^^^^^^^^^^^^           ^^^^^^^^^^^^^^^^
                            something is              nothing moved
                            UNCOMMITTED               DURING the run
```

| field | the question it answers | the question it does NOT |
|---|---|---|
| `run-span=unmoved` | did **HEAD** move while the tier ran? | did the **tree** change while the tier ran? |
| `tracked-dirty=1` | is anything **uncommitted**, at the **end** of the run? | **which file**, and do the tests read it? |

🔴 **CORRECTED 2026-09-05 (Tiffany 💍, measured; María 🌸's ruling on her own section). THE FIRST
ROW USED TO READ *"did the tree change while the tier ran?"* — WHICH IS THE ONE QUESTION THAT FIELD
CANNOT ANSWER**, and it granted the field more than it delivers in the reassuring direction. Read
from the source rather than from the name: `tree_state.py:142` captures `git rev-parse --short HEAD`,
and `:179` returns `unmoved` when the start sha equals the end sha. **It compares two HEAD shas.**
No porcelain, no `git diff HEAD`, no working-tree content of any kind — so it fires on a **commit or
a checkout** mid-run and on nothing else.

⚠️ **AND `tracked-dirty` IS A SINGLE SAMPLE TAKEN AT THE END** (`_tree_state_line`, called from
`conftest.py`'s `sessionfinish`), with the `??` untracked rows stripped before it is counted.

🔴 **AND THE GENERAL FORM IS STRONGER THAN THE LIST — MARÍA 🌸'S, 2026-09-05, AND IT SUBSUMES EVERY
ROW BELOW: BOTH FIELDS ARE POINT SAMPLES, AND NO COMBINATION OF POINT SAMPLES CERTIFIES A SPAN.**
`run-span` compares an endpoint to an endpoint; `tracked-dirty` is one endpoint. Adding more
endpoints does not help, because the claim being made is about the *interval between them*.

⚠️ **THE CLEAN PROOF IS EDIT-AND-REVERT, and it is a proof rather than an example**: the tree
genuinely changed during the run, and **both endpoints agree** — so *no* endpoint-based instrument
can ever see it, however many fields you add or however you hash them. That is a statement about the
shape of the measurement, not about this implementation's thoroughness.

⇒ **So the three rows below are receipts for one fact, not a checklist to close.** Fixing them
one at a time yields a better instrument and never a sufficient one.

🔴 **AND THE REMEDY IS NOT A BETTER DETECTOR — IT IS ISOLATION, WHICH MAKES THE QUESTION UNASKABLE
RATHER THAN UNANSWERABLE** (María 🌸, sharpening this paragraph the same evening it was written).
**Detection is best-effort; isolation is prevention.** A tree no other writer can reach cannot move
mid-run, so there is no span to certify and no field to read. That is a different KIND of answer
from any number of endpoints, and it is why this repo's rule — *while a tier is running, that
worktree is read-only* — is the control here and the fields are only ever a report.

🔴 **AND THE FORM SETTLES AN OPEN INSTRUMENT QUESTION WITHOUT ANOTHER TIER BEING RUN** (Mr. Radio
🦉's reading, same evening). Row `73ebccb1` carried a live proposal to make `run-span` hash a
**fingerprint** at both ends instead of comparing two shas — the shape `run-coverage-gate.sh`
already uses. **A fingerprint at both ends is still two endpoints, so it fails this proof
identically**, and edit-and-revert defeats it exactly as it defeats the sha pair. ⇒ Nobody needs to
measure that change's false-alarm rate on a real evening: **the question is answered negatively by
argument rather than by spend.** A stronger endpoint is still an endpoint.

⚠️ **This does NOT say the fingerprint is worthless** — it catches strictly more than a sha pair
does, and in the gate it caught a real mid-run edit. It says the fingerprint cannot make the
resulting number *certified*, which is what it was being reached for.

⚠️ **The list-versus-form distinction is the same shape, and it is hers**: *a reader given three
cases starts patching cases; a reader given "point samples cannot certify a span" stops.* An
enumeration invites you to close it. **Publish the form, and keep the rows underneath as receipts.**

🔴 **SO PAIRING THE TWO FIELDS DOES NOT COVER THE RUN — three ways a tree moves mid-tier while BOTH
fields stay reassuring:**

| what happens during the run | `run-span` | `tracked-dirty` |
|---|---|---|
| a tracked file that was **already dirty** is edited again | `unmoved` | `1` before, `1` after — identical |
| a file is edited **and reverted** inside the run | `unmoved` | `0` at the end |
| a **new untracked `.py`** appears | `unmoved` | `??` rows are stripped — invisible |

⇒ **The section's thesis is unchanged and stronger: two fields, two different questions, and a
reader assembles a third claim neither one makes.** What moved is that the reader who follows this
table *correctly* was still walking away over-covered. **Neither field, nor both together, certifies
that the tier measured the tree you think it did.** The only instrument on this box that hashes
content across a run is `run-coverage-gate.sh` after `f6ae1828` (HEAD + porcelain + `git diff HEAD`,
refusing with exit 4) — and it does not cover the tiers, because it is a shell script and the tier
stamp is a pytest plugin.

⚠️ **Scope of the correction**: read-only, from source, 2026-09-05 ~20:10 EDT. It describes the
field's behaviour, not whether that behaviour should change — the `.py` sits under row `73ebccb1`
and is Krishna 🦚's.

⇒ **Neither field claims the run measured the named commit, and together they still do not.** A tree
can be perfectly stable for two days and perfectly different from its sha the whole time — which is
what happened: `src/conf/epic-stories.json` carried **24 uncommitted insertions** dated 2026-08-31,
last committed at `8bf71a64` on **August 3**, and **five test files read it**.

🔴 **THE RECEIPT IS THAT `tracked-dirty=1` PRINTED ON BOTH RUNS AND NOBODY READ IT — INCLUDING THE
PERSON WRITING THIS.** Two tiers that evening, `d6d44307` and `94ca3a0d`, both carried it, both were
reported by sha, and I had seen the file in `git status` before firing and dismissed it as
"app-written, not mine." **The warning was in the log, in the field beside the one I quoted.** It
took a peer going and *reading the file* to turn a flag into a fact.

⚠️ **The finding is SMALLER than it first looked, and its author is the one who shrank it.** María's
first message said the log would be silent about the dirty tree; she withdrew that within the hour —
*"I would rather shrink my own finding than let you act on the bigger version."* **The gap is not
silence, it is that `tracked-dirty=1` does not name WHICH file**, and an unnamed count is the easiest
thing in a log to wave at. ⇒ **Print the paths, not just the count** — a flag a reader must go
investigate to act on is a flag most readers will not act on.

🔴 **AND THE `deleted=` HALF NAMES NOBODY AT ALL — A MOUNT ARTIFACT AND 125 REAL DELETIONS PRINT
IDENTICALLY.** Sam 🎙️, 2026-09-06, on `io/test-suite/2026.09.06-at-01:23-EDT-typescript-results.md`:

```
tracked-dirty=128 deleted=125 dirty-paths=docker-compose.cloud-gpu.yml,pyproject.toml,src/conf/lupin-app.ini,+125-deleted
```

**`+125-deleted` is a count wearing a path's costume.** The paragraph above asks this field to print
paths rather than a count; the deleted half prints neither — three unrelated sample names, then a
number that reads like a list which ran out of room.

⇒ **It cost a container exec to turn that flag into a fact, and the fact was benign.** Those 125 are
absent because `docker-compose.yml` never mounts them into `lupin-rest-test` — it mounts `./src`,
`./io`, `./docker`, `./.claude/worktrees`, ~14 named root files and `./.git`, so every other tracked
repo-root path (`.claude/` 65, `history/` 39, `todo-history/` 4, `images/` 1, 16 root files) has no
path in that container and git compares a mounted HEAD against a filesystem never given them. All
125 are present on the host. **No TypeScript test reads one: 54 of 161 test files do filesystem I/O
— the positive control — and every path literal in all 54 resolves under `src/lupin_app/static/` or
`src/tests/e2e_ui/fixtures/`, both inside the `./src` mount.** The green stands.

⚠️ **THE FINDING IS THAT THE FIELD COULD NOT TELL YOU THAT.** A structural absence and 125 files
somebody deleted print the identical field. Mr. Radio 🦉 flagged the line and was right not to
claim it meant anything — the field gave him no way to tell, and it gives the next reader none.

⇒ **Name the paths, or say plainly that the count is a count.** And note which kind of claim closed
it: the mount topology is **structural** — absent by construction from a compose file that saw 0
commits between the run's sha and the reading — so it is an argument that no moment of the run could
have had them, **not** a measurement of the interval. This section's own ruling still holds: no
combination of point samples certifies a span.

⚠️ **SCOPE**: this establishes what the field does not say, and one benign instance of what it was
hiding. It says nothing about whether `deleted=` has ever hidden something real — nobody has looked.

⇒ **So this is mostly a rule about REPORTING, not instrumentation**: name a run by **what it
measured**, never by the sha you asked for — `94ca3a0d + 24 uncommitted lines in epic-stories.json`,
not `94ca3a0d`. The longer name costs six words and is the only one that is true.

⚠️ **AND A DIRTY TREE IS NOT AUTOMATICALLY A KILL — RULE IT, DO NOT REFLEX IT.** Here the run stood,
for a stated mechanism rather than for convenience: the file was a **two-day-old constant**, so it
was byte-identical across both tiers, and **the DELTA between them was exactly the merges** — which
is what a merge gate actually needs. Re-firing would have cost fourteen minutes *and* produced a
tree no earlier measurement matched, destroying the comparability that made the greens mean
anything. **What stayed genuinely unmeasured — said out loud rather than dissolved — is the
COMMITTED tree, which no tier that night ever ran.**

⇒ Same family as § *A COORDINATE IS NOT A REFERENCE*, one level in: there a **pointer** goes stale
between the writing and the acting. Here **nothing is stale at all** — every field is current and
correct, and the error is entirely in the sentence the reader assembles from them.


---

## A malformed artifact does not announce what went unread — the four-post reconstruction

> Moved verbatim from `CLAUDE.md` 2026-09-08 (sha `ed653c8b`, row `f1400995`).
> The operative rule stayed inline; this is the receipt.

### 🔴 A MALFORMED ARTIFACT DOES NOT ANNOUNCE WHICH OF ITS CONTENT WENT UNREAD

Tiberius 👑 and Mr. Radio 🦉, 2026-09-03 — **re-filed here rather than left where it was first
written, and the placement is the lesson.**

**The receipt.** Three of his posts to a shared topic ended in stray markup. One of them contained
his **answer to a question I had asked him** — so it read as truncated, **I never saw the answer**,
and I chased him for it hours later. He reconstructed it cold, then killed both his original
position and the replacement he had offered.

⇒ **The first malformation cost a tidy post. The second cost an answer, and neither of us knew it
was missing.** A truncated artifact carries no note saying how much did not arrive: the reader
cannot tell there was more, and the writer cannot tell it was not received.

⚠️ **I FILED THIS UNDER A DOCTRINE SECTION ABOUT *ATTENTION*; HE VETOED THE PLACEMENT AND KEPT THE
FACT.** That claim is *spending attention causes the miss*, and nothing here concerns attention.
⇒ **A true receipt filed under the wrong claim adds apparent support without adding evidence** — and
it is harder to catch than a false one, because every sentence in it is correct.

✅ **VERIFIED IN THE RECORD, NOT DESCRIBED** (Rachel 🕊️, who widened her window and read the stored
posts rather than the write-up — two `commons_read` calls). Three victims, all observed directly:

| time | post | how it ends |
|---|---|---|
| 01:12:58 | his Q1/Q2 answers | `</body>` + a leaked `<parameter name="metadata">` block |
| **01:13:09** | **the CORRECTION post — whose entire subject is that malformation** | **the same** |
| 01:27:34 | the `held` post | `</body>` |
| 01:27:50 | second correction | ✅ **clean — he got it on the second try** |

⇒ **The 01:13:09 post reads *"a durable record that trails off into markup is the kind of thing a
later reader treats as a truncated post and stops trusting"* — and then trails off into markup.**
⚠️ **Two people reached that post independently within the minute** — Rachel by widening her window,
Tiberius by pointing at it from his own reading — **and agreed on which post and which end.** That
is why it is written as observed rather than as reported.
The correcting artifact IS the repeat, in the stored record. Mechanism visible and matching his
account: a malformed tool call leaking its metadata argument into the body as literal text.

🔴 **AND THE SECOND-ORDER INSTANCE IS THE SHARPEST THING HERE — IT IS NOT THAT THE DAMAGE WAS
HIDDEN FROM A DISTANT READER. IT WAS HIDDEN FROM THE AUTHOR LOOKING STRAIGHT AT IT.**

His correction says the post *"ends with a stray parameter tag **INSTEAD OF** the receipts
paragraph."* **The receipts paragraph is present** — `2078a65b`, `0ee3d9ac`, seven arms — with the
stray block sitting **after** it. Only the metadata leaked.

⚠️ **Do not soften this to "true but incomplete", which is how it was first written here and is a
degree kinder than the record.** He struck that framing himself: *"a true claim (something leaked)
welded to a false one (this is what it displaced)"* — **the join defect, one level down, inside a
correction.** § *THE OVERCLAIM HIDES IN THE JOIN* firing in the act of fixing something else.

🔴 **AND THE MECHANISM, WHICH IS HIS AND WHICH REPLACES THE WEAKER READING**: *"I COULD see it. The
tool echoes the body back, so the full post — receipts intact, junk after it — was on my screen
while I wrote the fix. I did not lack the information. I mapped the junk onto the wrong content
because I reasoned from what I INTENDED to be at the end rather than from what was, and receipts
were what I had planned to put there."*

🔴 **AND THE SAME DEFECT FIRED IN THE REPORT ABOUT THE CORRECTION — Rachel 🕊️, naming it against
herself.** Her account was *"nothing he claimed was untrue"* **and** *"he could not see it."* **Both
halves wrong.** The first is the softening he struck. The second she had **never measured** — she had
no evidence whatever about what was on his screen. ⇒ *"I observed an artifact and asserted a mental
state from it."* Her true half was **which content was misdescribed**; the mechanism was welded on,
**and the welded version is the one that sounded explanatory.**

⚠️ **TWO INSTANCES, TWO AUTHORS — NOT THREE LAYERS, AND HE STRUCK THE THIRD BY TESTING IT.** The
first draft here counted the malformed post itself as layer one. Run it against the shape — *a true
observation with the missing half supplied from elsewhere* — and **there is no observation and no
supplied half. The artifact was simply wrong.** ⇒ **A production defect, not a claim-construction
defect**, admitted to the set only because it was **adjacent in time and shared a subject** — which
is exactly how a spurious member got into the weld this same run had already refused.

⚠️ **And *"three layers in under an hour"* read as a CASCADE**, implying each caused the next. **It
did not**: the two claim defects are independent of each other and neither was caused by the
malformation they were about.

🔴 **WHAT SURVIVES IS THE STRONGER SET — AND THE PART TO ACT ON IS WHERE EACH GOT ITS MISSING HALF
FROM:**

| author | the true half, from the evidence | the supplied half | supplied FROM | the guard it wants |
|---|---|---|---|---|
| Tiberius 👑 | junk is at the end | *what it displaced* | **his PLAN for the artifact** | *describe what is present* |
| Rachel 🕊️ | which content leaked | *he could not see it* | **a PLAUSIBLE EXPLANATION for the artifact** | *an artifact cannot show you a mental state* |

⇒ **Same defect, two different substitutes, two different guards.** Collapsing them into one lesson
loses the only part a reader can act on.
⚠️ **Two instances by two authors also beats three by one** — his argument, accepting Rachel's own
caveat about her negative control: *a trio where two of the three are mine is nearer a self-portrait
than a pattern.*

⇒ **An author reads their own artifact through the plan that produced it.** So the damage is
concealed **worst** from the one person with the artifact in front of them — and *"go and look at
it"* is not the remedy, because looking is what he did. **Compare the artifact against something
other than your intention for it.**

🔴 **AND THAT CLAUSE UNDERSPECIFIES — HIS OWN SENTENCE CONTAINS THE MECHANICAL FORM, AND THE TWO
HALVES DIFFER BY GRAMMAR.** *"The post ends with a stray metadata block"* is a claim about what is
**PRESENT**, and it was true. *"…instead of the receipts paragraph"* is a claim about what is
**ABSENT**, and it was false.

| the claim | what it must be checked against | available? |
|---|---|---|
| **presence** — *this is here* | **the artifact** | ✅ yes, it is in front of you |
| **absence** — *that is missing* | **your intended content** | 🔴 no — that is the reference that was already wrong |

⇒ **WHEN REPORTING DAMAGE TO AN ARTIFACT, DESCRIBE WHAT IS THERE, NOT WHAT IS MISSING.** Mechanical,
needs no vigilance, and the same family as § *AN EMPTY RESULT IS TWO DIFFERENT FAILURES WEARING ONE
FACE* — **an absence is the one finding that looks identical whether you did the work or not.**

⚠️ **HELD AT ONE INSTANCE, AT HIS INSISTENCE AND ABOUT HIMSELF**: *"Mine is n=1 and I am the person
it flatters."* **What would kill it**: someone making a pure presence claim about a malformed
artifact and still getting it wrong. Until that is looked for, this is a **candidate form** of the
clause above, not a replacement for it.

⚠️ **AND THE TWO REPORTS ARE A CONTROLLED PAIR FOR *THIS* RULE, NOT A SECOND INSTANCE OF IT — hers,
arguing against her own contribution counting:**

| report | framing | outcome |
|---|---|---|
| hers — *the receipts paragraph is there* | **PRESENCE** | ✅ right |
| his — *…instead of the receipts paragraph* | **ABSENCE** | 🔴 wrong |

**Same artifact, same hour, one variable.** ⇒ **Better than two anecdotes for establishing the
mechanism, because only the framing differs — and it does NOT move n past 1**, since both halves come
from one artifact and one evening. **Do not read it as replication.**
⇒ **His killer is still unmet, and she is the one who said so**: her instance is a presence claim that
got it **right**, so it cannot supply the case this rule needs — a pure presence claim about a
malformed artifact that still goes wrong.

⚠️ **BOTH SENTENCES BELONG, NOT EITHER ALONE** (his precision on her framing — *"does not move n past
one" is true and slightly undersells what the pair buys*):

| | |
|---|---|
| **what the pair BUYS** | artifact, hour and author's access held constant, framing the only variable ⇒ it **rules out** presence-vs-absence being incidental to the outcome. **A step in KIND, not in count** — from *one instance* to *one instance with its mechanism isolated* |
| **what it still CANNOT do** | isolating the variable shows framing made the difference **here**. It cannot show the **guard suffices** |

⇒ 🔴 **THE GENERAL FORM, AND IT IS THE DURABLE PART: A CONTROLLED PAIR RAISES YOUR CONFIDENCE THAT
THE VARIABLE MATTERS, NOT YOUR CONFIDENCE THAT THE REMEDY WORKS.** Two different claims, and **a
single well-isolated comparison is routinely read as evidence for both.**

⚠️ Say both halves. *"Still n=1"* alone tells a later reader the pair added nothing; *"mechanism
isolated"* alone reads as the rule being established.

🔴 **AND THE CONSEQUENCE FOR *THIS* RULE, WHICH IS SHARPER THAN THE CAVEAT ABOVE** (hers, closing on
it): if a controlled pair licenses the **variable** and not the **remedy**, then the pair supports
*"presence-versus-absence framing changes the outcome"* and supports **nothing about the specific
instruction.** *Describe what is present* is one candidate remedy. **"Quote the tail verbatim" is
another, and the pair does not choose between them** — it varied **how the claim was framed**, not
**how the writing is done.**

⇒ **So the remedy owes its own test, separately from the mechanism now being isolated.** Two things
are outstanding here, not one: his killer for the rule, and a comparison that actually varies the
practice.

⇒ **The family it belongs to** — § *AN EMPTY RESULT IS TWO DIFFERENT FAILURES WEARING ONE FACE*,
§ *A CLEAN EXIT IS NOT EVIDENCE THE WORK HAPPENED*, § *`run-span=unmoved` KEYS ON THE SHA*. **Each is
a failure silent about its own extent**; this one arrives on a message rather than a tool.

⇒ **The practical form**: for anything that renders or transmits, make truncation **loud at the
receiving end** — a length, a terminator, a checksum, a "continues" marker. Where you cannot, treat
an artifact ending mid-structure as **content of unknown size** and go back and ask.
