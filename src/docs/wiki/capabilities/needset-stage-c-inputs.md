---
capability: needset-stage-c-inputs
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_mcp.reuse_needset.stage_c.norm_text@fde4150a11
  - lupin_mcp.reuse_needset.stage_c.text_index@f0867ba7b2
  - lupin_mcp.reuse_needset.stage_c.git_source_lines@87d436d86a
  - lupin_mcp.reuse_needset.stage_c.check_pins@62d4beb03b
  - lupin_mcp.reuse_needset.stage_c.read_pairs@aebbcd7cce
  - lupin_mcp.reuse_needset.stage_c.prepare_side@51ce9ec8a8
  - lupin_mcp.reuse_needset.stage_c.split_pairs@0faf262a52
  - lupin_mcp.reuse_needset.stage_c.audit_sides@f2e3e35359
  - lupin_mcp.reuse_needset.stage_c.with_headroom@9c1edce1b9
  - lupin_mcp.reuse_needset.stage_c.budgets_for@4da210b405
  - lupin_mcp.reuse_needset.stage_c.plan_of@ff14345471
  - lupin_mcp.reuse_needset.stage_c.cue_of@efe527dacc
---
# Need set: the judge-only run, inputs and plan

The judge-only run asks the judge about the real labelled pairs of the 25 October first-thousand trial. Each pair has two sides, a and b, held as source text. Drafting and judging are on [[needset-stage-c-drafting]], the command on [[needset-stage-c-command]], the scoring on [[needset-stage-c-figures]].

## Finding the sides
- `norm_text` puts a definition's text in a form two copies share. `text_index` maps that text to the ids of the index records that hold it.
- `git_source_lines` reads a file as it stood at a commit, so each side is matched at the answer key's source commit.
- `check_pins` checks the label files and the answer key against their pinned hashes. It raises `CONTROL_LABELS_CHANGED` for any that differ.
- `read_pairs` reads every pair of the three strata with its label, raters and side texts.
- `prepare_side` prepares a record the way the lookup shows it to the judge, with its stored purpose line and the sendable screen.
- `split_pairs` keeps the pairs the judge can read and refuses the rest with every reason. A side may match no record, be dropped by the screen, or lack a purpose line, or both sides may be one record.
- `audit_sides` counts what became of the sides and names each one that did not reach the judge in full.

## Planning
- `with_headroom` adds 5 percent to a planned call count, rounded up. `budgets_for` derives the drafting and posting budgets from the pairs that will run, and reports any budget below its plan.
- `plan_of` describes the run without a call. `cue_of` marks a pair whose need shares a name piece with side b's record.

## Don't
- Don't read a refused pair as a miss. A stated rule removed it before drafting.
