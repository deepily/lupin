# Doctrine: merge-gate wording audit

Where the workflow documents blur a working-branch merge with a PR to main.

Rick ruled on 14 November 2026. End-to-end and integration run only before a PR to main. A working-branch merge needs the unit and census checks green, plus review.

## Why it keeps coming back

On 14 November a manager froze working-branch merges for about two hours. The aim was a full run of the 15-row pyramid. It could not finish before the host powered off, and three reviewed commits waited.

The documents invite this.
- The repo `CLAUDE.md` defines one merge gate, under "PR merge requirements". It says nothing about the working branch.
- The SWE-team charters make the tester's integration and end-to-end run part of every commit gate.
- "Green AND reviewed" never says what green means. A manager reads it as the strictest gate it can find.

## Population searched

| Population | Files |
|---|---|
| lupin tracked `*.md`, minus `src/rnd`, `src/cosa/rnd`, `history`, `todo-history`, `src/cosa/history`, `src/docs/post-games` and the receipts archive | 1,032 |
| planning-is-prompting `workflow/` (`.md`, `.sh`, `.py`) | 164 |
| `~/.claude` `CLAUDE.md`, `commands/` and `skills/` | 15 |
| **Total** | **1,211** |

The searches were fixed-string (`git grep -F`, `grep -rnF`). The terms:
- `pyramid`, `merge gate`, `final merge gate`, `PR merge requirements`
- `merge to main`, `to main`, `before merg`, `working branch`
- `once green`, `green AND`, `all green`
- `e2e`, `E2E`, `integration test`, `full suite`, `all tiers`

Every match was read. The table lists the passages that say what to run or what "green" means. A page that only describes a suite is left out.

Limits: `git grep` cannot see untracked files. A phrase outside those terms would be missed.

## The passages

The verdicts:
- **over**: tells a seat to run integration or end-to-end before a working-branch commit or merge.
- **blurs**: says "merge gate" without saying which merge.
- **undefined**: says "green" without defining it.
- **ok**: scoped correctly.

| # | Path | Heading | Quote | Verdict |
|---|---|---|---|---|
| 1 | `CLAUDE.md` | PR merge requirements | "All must pass before merging to main, in this order." | blurs: right scope, but it is the only merge gate in the file |
| 2 | `CLAUDE.md` | Testing venues, :8000 suites that qualify | "`src/tests/run-integration-tests.sh` (final merge gate)" | blurs |
| 3 | `CLAUDE.md` | Testing, table | "**final merge gate**; always `--bg`" | blurs |
| 4 | `CLAUDE.md` | PR merge requirements, On failure | "do not merge. Fix the failing tests, then re-run the full suite." | ok under a PR to main; reads as universal |
| 5 | `CLAUDE.md` | Testing, Before you ask for review | "run `src/tests/run-census-guards.sh` beside the tests of the files you changed" | ok: the census half of the working-branch gate |
| 6 | `src/tests/README.md` | Pre-Merge Test Checklist | "must pass before merging any branch to main." | ok |
| 7 | `src/docs/notification-api/17-testing-guide.md` | testing guide | "must pass** before merging to main" | ok |
| 8 | `.claude/skills/spin-up-swe-team/SKILL.md` | Run the gate | "integration/e2e green" then "commit only on the user's word" | over, and it makes the user the commit gate |
| 9 | same | Notes | "Hard commit gate**: green AND adversarially-reviewed" | undefined |
| 10 | `.claude/commands/spin-up-swe-team.md` | Run the lifecycle and gate | "tester integration/e2e green" then "Commit **only on the user's word**" | over, same two defects |
| 11 | `src/docs/wiki/capabilities/utils-review-verdict-gate.md` | the page | "names the tree, the census-guard result and Merge or Fix" | ok: the model for the working-branch gate |
| 12 | planning-is-prompting `workflow/swe-team-roles.md` | Manager charter, Expectations and gates | "tester posts integration/e2e green" before "you (the Manager) then commit AND merge to the working branch" | **over**: the main source |
| 13 | same | Tester charter, Expectations and gates | "Post **integration/e2e green** ... as the third leg of the gate." | **over** |
| 14 | planning-is-prompting `workflow/swe-team-spin-up.md` | Lifecycle gates | "green AND adversarially-reviewed before any commit" | undefined |
| 15 | planning-is-prompting `workflow/manager-autonomy.md` | The user is not the commit/merge gate | "Once work is green AND adversarially-reviewed, the Manager commits and merges to the working branch" | undefined |
| 16 | planning-is-prompting `workflow/session-end.md` | intro and the commit step | "the quality gate (green AND reviewed)" | undefined |
| 17 | planning-is-prompting `workflow/branch-pr-and-merge.md` | Test Suite Verification | "Run integration tests (optional - may require server/external services)" | ok: a PR flow |
| 18 | `~/.claude/CLAUDE.md` | Manager spawn/harvest autonomy | "commit + merge to the working branch once green AND reviewed" | undefined |

Counts: 18 passages.
- **Over**: 4 (rows 8, 10, 12, 13).
- **Undefined**: 5 (rows 9, 14, 15, 16, 18).
- **Blurs**: 3 (rows 1 to 3).
- **Ok**: 6 (rows 4 to 7, 11, 17).

## The one wording

> **Two kinds of merge.** To the working branch, a manager merges on its own authority. The unit tier must be green for the files changed, `run-census-guards.sh` must be green, and a reviewer's verdict must be Merge. Integration, end-to-end and the other `:8000` rows are not part of it. A PR to main needs all 15 rows. "Green" in "green AND reviewed" means the working-branch gate.

## What the commit changes

All of it is in the lupin repo. It adds the "Two kinds of merge" section to `CLAUDE.md`. It rewords rows 1 to 3. It corrects rows 8, 9 and 10.

Row 4 stays, because it sits under the PR to main heading, which now says so.

## What it does not change

Rows 12 to 16 and 18 live in the planning-is-prompting repository and in `~/.claude/CLAUDE.md`. This commit leaves them alone. The proposed edits:
- Rows 12 and 13: take "tester posts integration/e2e green" out of the commit gate. Put it under "before a PR to main".
- Rows 14, 15, 16 and 18: after "green AND reviewed", add "green means the unit tier and census guards for the files changed".

## Not measured

- Whether another repo's `CLAUDE.md` carries the same wording. Only lupin and the three global locations were searched.
- Whether a manager's brief or memento restates the full pyramid. A search does not find those.
