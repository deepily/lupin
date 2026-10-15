---
capability: expeditor-cli-and-mock-submit
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.agents.runtime_argument_expeditor.cli_help.build_parser@b969abeca4
  - cosa.agents.runtime_argument_expeditor.xml_models.ExpeditorResponse@f2d6583f7a
  - cosa.agents.runtime_argument_expeditor.xml_models.ArgConfirmationResponse@700d581ef8
  - cosa.agents.test_harness.mock_submit.MockJobArgs@265b135e36
  - cosa.agents.test_harness.mock_submit.match_voice_command@305128e7af
  - cosa.agents.test_harness.mock_submit.validate_ranges@518aa0fbc3
  - cosa.agents.test_harness.mock_submit.build_expeditor_test_job@93184abfaa
---
# Expeditor response models, help text and mock submit

The runtime argument expeditor ([[runtime-argument-expeditor]]) has two small XML models and a help builder. The mock job command uses the expeditor to test routing without a real agent.

## What it does
- `ExpeditorResponse` holds `all_required_met`, `args_present` and `args_missing`, all strings. Empty tags become empty strings.
- `ArgConfirmationResponse` holds an `action`, an `arg_name` and a `new_value`. The action is approve, modify or cancel.
- `build_parser` builds an argparse parser for an agentic command from its contract entry. Each required user argument becomes a required `--option`, and mapped targets become optional ones.
- `MockJobArgs` is the argument model of the mock job command. It bounds iterations, sleep and failure probability, and may carry a `voice_command` and a `force_failure_mode`.
- `validate_ranges` raises `ValueError` when a minimum exceeds its maximum.
- `match_voice_command` returns the first command whose keywords all appear in the voice command, skipping the mock command. It then tries the presentation, podcast and research cases, and returns `None` if nothing fits.
- `build_expeditor_test_job` runs a voice command through the expeditor and builds a dry-run job of the matched command.

## Don't
- Don't expect `build_expeditor_test_job` to return when the user cancels. It raises `SubmitRefused`.
- Don't expect a match to be exact. `match_voice_command` is a keyword test.
