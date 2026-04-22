# 95 — PEFT Training Data Execution Log

**Tracks**: Implementation step 17 of the plan — PEFT voice routing training data generation. GPU training runs are USER-RUN per memory rule; this plan generates the data.

**Design doc**: [`13-peft-training-data-plan.md`](13-peft-training-data-plan.md)

**Precondition**: TFE scaffolding complete (command registered in agent-router-agentic-commands.json).

---

## Step 17a: Template authoring

**Status**: TODO

| Sub-step | Status | Commit | Notes |
|----------|--------|--------|-------|
| Create `src/conf/training-templates/test_fix_expediter-templates.txt` | TODO | — | |
| Category 1: Direct commands (15 templates) | TODO | — | See design doc |
| Category 2: Contextual with suite reference (20 templates) | TODO | — | |
| Category 3: Conversational / polite (15 templates) | TODO | — | |
| Category 4: Goal-oriented / indirect (15 templates) | TODO | — | |
| **Total ≥ 65 templates** | TODO | — | Minimum per skill |
| Review templates for natural variation | TODO | — | No duplicates, realistic phrasings |

---

## Step 17b: Command registration verification

| Sub-step | Status | Notes |
|----------|--------|-------|
| `"agent router go to test fix expediter"` in `agent-router-agentic-commands.json` | TODO | Done during step 6 scaffolding — verify here |
| `test_command_json_registered()` unit test passes | TODO | |

---

## Step 17c: XML coordinator generation run

| Sub-step | Status | Notes |
|----------|--------|-------|
| Dry-run xml_coordinator to validate template syntax | TODO | |
| Execute: `python -m cosa.training.xml_coordinator --agent test_fix_expediter --templates conf/training-templates/test_fix_expediter-templates.txt --output data/training/test_fix_expediter/ --split 80/10/10` | TODO | |
| Verify `train.xml` created with N examples | TODO | |
| Verify `test.xml` created | TODO | |
| Verify `validate.xml` created | TODO | |
| Assert no multi-placeholder expansion bugs (regression from Session 389 fix) | TODO | |

**Generation counts**: train=_(TBD)_ / test=_(TBD)_ / validate=_(TBD)_

---

## Step 17d: Unit test for generated data

| Sub-step | Status | Notes |
|----------|--------|-------|
| Create `src/tests/unit/test_tfe_training_data.py` | TODO | |
| `test_templates_file_exists_and_nonempty` (≥ 65 lines) | TODO | |
| `test_command_json_registered` | TODO | |
| `test_generated_xml_has_correct_command` | TODO | Skip if data not generated yet |
| `test_no_duplicate_templates` | TODO | |
| `test_no_regression_on_other_agents_templates` | TODO | Existing agent templates unchanged |

---

## Step 17e: Hand-off to user for PEFT training

**GPU workloads are USER-RUN ONLY per `feedback_never_grab_gpu` memory. Claude does NOT execute the trainer.**

### User instructions (to be sent when data is ready)

```
PEFT training data for TestFixExpediter is ready. To train:

1. Sanity run (1% of full training, ~5-10 minutes on your GPU):
   ./src/scripts/run-agentic-intent-training.sh test

2. If sanity run passes, full run (~3-4 hours on your GPU):
   ./src/scripts/run-agentic-intent-training.sh full

3. Report back:
   - Validation accuracy on TFE command (target: >95%)
   - Validation accuracy delta on other agents (target: <2% regression)
   - Any errors during training
```

### Results from user run (to be filled in)

| Run | Status | Accuracy on TFE | Max regression on others | User notes |
|-----|--------|-----------------|--------------------------|------------|
| Sanity | TODO | — | — | |
| Full | TODO | — | — | |

---

## Acceptance criteria

- [ ] ≥ 65 templates authored
- [ ] Command registered in agent-router-agentic-commands.json
- [ ] xml_coordinator.py generates valid train/test/validate XML
- [ ] Unit tests for generated data pass
- [ ] User sanity run passes (no errors)
- [ ] User full run: TFE accuracy >95%
- [ ] User full run: no regression >2% on any existing agent
- [ ] Update TODO.md: PEFT training data step complete

## Rollback criteria

If user reports regression >2% on any existing agent:
1. Remove TFE templates from the training set
2. Re-run xml_coordinator without TFE
3. Ask user to re-run trainer
4. Re-design TFE templates with fewer/more-specific phrasings
5. Retry generation and training

---

## Deviations from PEFT plan

_(add entries here as they occur)_

---

## Open follow-ups

_(add entries here as discovered)_
