# What's New

The full narrative for the current release. The README carries a short summary and links here.

The narratives for earlier releases are archived at the end of [VERSION-HISTORY.md](VERSION-HISTORY.md), under "Full release narratives". For the older per-feature changelog, see [CHANGELOG.md](CHANGELOG.md).

---

## What's New in v0.2.3 — a decision proxy that learns, the reuse backlog judged, and the background jobs under one switchboard

v0.2.3 ran from 4 to 17 November 2026: 1,098 commits (823 without merges) across 2,027 files. It took three things v0.2.2 left open and finished them. The decision proxy's 18 known defects were fixed, and its trust model became a setting. The reuse checker's backlog was judged and acted on, with the last of it still being judged. Every background job was put behind a switch the owner can see and flip.

**The decision proxy**

- **Eighteen defects fixed**. All 18 numbered defects from the list in the v0.2.2 explainer are closed, each reviewed before it landed. They include organic decision rows, and an error-rate feature and demotion for the regression model. Calibration is conformal on out-of-sample predictions, free-text accuracy is true cosine, and multiple-choice and batch answers are scored. The admin guide now matches the code.
- **A trust model you can choose**. The trust model is a setting with three choices: a plain count, a beta model, or a Bayesian logistic regression. The default is still the plain count. The regression is fed from decisions a person has ratified, and its state is kept in the database.
- **Accuracy not yet re-measured**. Nobody has re-run the accuracy report since the fixes, so this release claims no new accuracy figure. The [online preference-learning explainer](src/rnd/v0.2.3/2026.11.16-online-preference-learning-pm-explainer.md) says what is and is not measured.
- **One strategy builder**. The SWE team, the bug-fix expediter and the decision proxy now build their strategies through the same code.

**The reuse backlog judged**

- **Rulings for the backlog**. Rulings already saved were rescued first. Opus then judges the remaining definitions under a daily budget, and that work continues after this release. Every ruling names the model that made it. A back-fill closed the gap of definitions that had no outcome line.
- **The duplicate-check findings triaged**. Seats worked through 274 functions on 14 November and 356 findings on 16 November. Of the 356, 323 were distinct, 14 were duplicates and 19 should extend an existing symbol. The fixes for those 33 follow this release.
- **A wider search**. The reuse search now expands each need before it searches, with 128 candidates per query and a fusion depth of 512. On whole lists it finds between 101 and 122 of the 124 known answers.

**Background jobs under one switchboard**

- **A switch on every job**. All 24 jobs in the registry have a switch, and the running job honours it. This was checked live on 14 November.
- **Plain descriptions**. Every job's card opens with a short description of what the job does.
- **One jobs list**. Both web clients show one merged list of jobs, in place of the separate scheduled-jobs list.
- **Quieter workers**. Worker seats no longer speak routine updates by default. Urgent notices are still spoken.

**Platform and operations**

- **A test server on the cloud machine** for tests that change data, with a deploy that checks itself.
- **A smaller backup**. The backup went from 22.3 GB to 5.3 GB. The database dump is compressed, input and output rows no longer store embeddings, and notification vectors are cleared.
- **A merge queue for managers**.
- **Self-cleaning job worktrees**. A test-fix job's worktree removes itself once git no longer records it.
