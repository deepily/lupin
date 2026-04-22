# 13 — PEFT Voice Routing Training Data

Per `feedback_voice_routing_training_data` memory: any new agent with a voice-driven submission path requires PEFT training examples generated via the XML prompt generator. Per `feedback_never_grab_gpu` memory: GPU workloads are USER-RUN only. This plan generates the data; the user runs the trainer.

## Why TFE needs training data

TFE's command string is `"agent router go to test fix expediter"`. The voice routing LoRA must map natural-language user utterances to this command string with >95% accuracy without regressing other agents. Without training data, the user cannot voice-submit a TFE job; they can only rely on the automatic watchdog path.

**Note**: The watchdog-triggered auto-dispatch path does NOT need voice routing — it's wired directly in code. Voice routing is needed only for the manual submission path (user speaks "run the test fix expediter on the last e2e failure" or similar).

## Deliverables

| Artifact | Path | Purpose |
|----------|------|---------|
| Command registration | `src/conf/agent-router-agentic-commands.json` | Canonical command string + job class path |
| Training templates | `src/conf/training-templates/test_fix_expediter-templates.txt` | 65+ natural-phrasing templates with placeholder substitution |
| Generated training XML | `src/data/training/test_fix_expediter/*.xml` | Output of xml_coordinator.py |
| Validation script hook | `src/cosa/training/xml_coordinator.py` (existing) | Generator invoked as code task |
| Validation unit test | `src/tests/unit/test_tfe_training_data.py` | Asserts generated XML shape + minimum count |

## Template authoring

Templates live in `src/conf/training-templates/test_fix_expediter-templates.txt`, one per line. Each template uses `PLACEHOLDER_*` tokens for variation.

Minimum: 65 unique templates. Categories and target counts:

### Category 1: Direct commands (15 templates)
```
run the test fix expediter
execute test fix expediter
launch TFE
start test fix expediter
fire up the test fix expediter
invoke test fix expediter
initiate TFE
begin test fix expediter
kick off the test fix expediter
trigger test fix expediter
go TFE
run TFE
execute TFE now
launch test fix expediter immediately
start TFE now
```

### Category 2: Contextual with test suite reference (20 templates)
```
run the test fix expediter on the last PLACEHOLDER_SUITE_NAME failure
fix the failing PLACEHOLDER_SUITE_NAME tests with TFE
try to auto-fix the PLACEHOLDER_SUITE_NAME failures
auto-repair the failing PLACEHOLDER_SUITE_NAME tests
run TFE against the most recent PLACEHOLDER_SUITE_NAME run
apply test fix expediter to the PLACEHOLDER_SUITE_NAME failures
ask TFE to handle the PLACEHOLDER_SUITE_NAME breakage
let TFE try to fix the PLACEHOLDER_SUITE_NAME failures
run test fix expediter on remediation snapshot PLACEHOLDER_SNAPSHOT_ID
fix the PLACEHOLDER_SUITE_NAME bugs with the test fix expediter
TFE the failed PLACEHOLDER_SUITE_NAME tests
auto-fix the PLACEHOLDER_SUITE_NAME suite
handle the last PLACEHOLDER_SUITE_NAME failures automatically
repair the broken PLACEHOLDER_SUITE_NAME tests with TFE
run TFE for the PLACEHOLDER_SUITE_NAME snapshot at PLACEHOLDER_SNAPSHOT_PATH
fix the failing tests in the PLACEHOLDER_SUITE_NAME run
auto-repair PLACEHOLDER_SUITE_NAME failures
run the test fix expediter against the PLACEHOLDER_SUITE_NAME run from PLACEHOLDER_TIMESTAMP
TFE the PLACEHOLDER_SUITE_NAME failures from earlier
fix the tests TFE
```

### Category 3: Conversational / polite (15 templates)
```
can you run the test fix expediter
please launch TFE
could you start the test fix expediter
would you run TFE on the last failure
please try to fix the failing tests with TFE
can you invoke the test fix expediter
would you launch TFE now
please execute test fix expediter
could you auto-repair the failing tests
would you mind running TFE
please run the test fix expediter on the snapshot
can you try TFE
would you start the test fix expediter
please have TFE look at the failures
can you kick off the test fix expediter
```

### Category 4: Goal-oriented / indirect (15 templates)
```
I want to auto-fix the failing tests
I need to repair the PLACEHOLDER_SUITE_NAME breakage
I'd like TFE to handle this
I want the test fix expediter to try
let's automate fixing the failures
I want to run auto-repair on the test run
I want the tests automatically fixed
let's have TFE take a shot at it
I want to try auto-fixing the failures
let's run TFE on this
I want to delegate the test repair to TFE
get the test fix expediter to try a fix
I want automated test repair
let's send this to TFE
I want TFE to handle the test failures
```

**Total: 65 templates across 4 categories.** This meets the skill's minimum; the coordinator may generate more variation via placeholder substitution.

## Placeholder substitution sources

| Placeholder | Sources |
|-------------|---------|
| `PLACEHOLDER_SUITE_NAME` | `e2e`, `integration`, `unit`, `smoke`, `websocket`, `presentation`, synonyms (`end-to-end`, `integration tests`, etc.) |
| `PLACEHOLDER_SNAPSHOT_ID` | Realistic TestSuiteJob ID format: `ts-abc12345` |
| `PLACEHOLDER_SNAPSHOT_PATH` | `io/test-suite/2026.04.10-at-14:53-e2e-remediation.json` |
| `PLACEHOLDER_TIMESTAMP` | `this morning`, `yesterday`, `at 2 AM`, `the 10:32 EDT run` |

The `xml_coordinator.py` already handles multi-placeholder expansion (per the memory fix in Session 389 — "Multi-placeholder expansion bug fix in xml_coordinator.py").

## Generation workflow (code task, no GPU)

```bash
cd /mnt/DATA01/include/www.deepily.ai/projects/lupin/src
python -m cosa.training.xml_coordinator \
    --agent test_fix_expediter \
    --templates conf/training-templates/test_fix_expediter-templates.txt \
    --output data/training/test_fix_expediter/ \
    --split 80/10/10
```

Expected output:
- `src/data/training/test_fix_expediter/train.xml` (~80% of examples)
- `src/data/training/test_fix_expediter/test.xml` (~10%)
- `src/data/training/test_fix_expediter/validate.xml` (~10%)

Coordinator also updates the aggregated dataset at `src/data/training/agentic-intent-training.jsonl` (if that's the pattern — verify against the most recent Session 389 memory).

## Validation unit test

`src/tests/unit/test_tfe_training_data.py`:

```python
def test_templates_file_exists_and_nonempty():
    path = cu.get_project_root() + "/src/conf/training-templates/test_fix_expediter-templates.txt"
    assert os.path.exists(path)
    with open(path) as f:
        lines = [l.strip() for l in f if l.strip() and not l.startswith("#")]
    assert len(lines) >= 65, f"Need at least 65 templates, got {len(lines)}"

def test_command_json_registered():
    path = cu.get_project_root() + "/src/conf/agent-router-agentic-commands.json"
    with open(path) as f:
        data = json.load(f)
    commands = [entry["command"] for entry in data]
    assert "agent router go to test fix expediter" in commands

def test_generated_xml_has_correct_command():
    """Run after xml_coordinator has generated the training data."""
    path = cu.get_project_root() + "/src/data/training/test_fix_expediter/train.xml"
    if not os.path.exists(path):
        pytest.skip("Training data not generated yet")
    tree = ET.parse(path)
    # Each example should map to the canonical command string
    for example in tree.iter("example"):
        target = example.find("target").text
        assert "test fix expediter" in target.lower()
```

## Handoff to user for training

After `xml_coordinator.py` completes successfully AND validation test passes, the plan hands off to the user:

**Claude cannot run the trainer.** Per `feedback_never_grab_gpu` memory, GPU workloads are USER-RUN only.

User runs:

```bash
# Sanity run (1% of full training, 5-10 minutes)
./src/scripts/run-agentic-intent-training.sh test

# Full run (~3-4 hours on user's GPU) — ONLY after sanity passes
./src/scripts/run-agentic-intent-training.sh full
```

Acceptance criteria (user reports back):
- Sanity run: no syntax errors, LoRA adapter saves successfully
- Full run: validation accuracy >95% on TFE command, no regression on other agent commands (presentation_generator, deep_research, podcast_generator, etc.)
- If regression observed: investigation task for the next session

## Risk: regression on other agents

Adding new training examples can shift the LoRA's decision boundary and regress previously-good commands. Mitigation:
1. Re-use all existing training data; TFE templates are additive only
2. Validation set holds out 10% of ALL agents, not just TFE
3. User reports regression deltas per agent in the execution log at `95-peft-data-execution-log.md`
4. If regression > 2% on any existing agent, roll back the TFE templates and redesign (fewer templates, more specific phrasings)

## Future extensions (not in MVP)

- **Auto-watchdog training path** — PEFT for the watchdog trigger phrases (e.g., "if the e2e fails, try TFE"). Not needed in MVP because the watchdog is code-wired, not voice-wired.
- **Interactive refinement** — ask the user to confirm ambiguous voice commands before dispatching TFE. Handled by the existing AskUserQuestion / confirmation pattern.
