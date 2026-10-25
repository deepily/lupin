---
capability: vertex-env-guards
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.utils.vertex_env.VertexEnvError@eff1c924ef
  - cosa.utils.vertex_env.assert_certifications_are_provenanced@672b4a2796
  - cosa.utils.vertex_env.assert_model_pin_agreement@a3fd62058f
  - cosa.utils.vertex_env.assert_no_hostile_env@916b66965f
  - cosa.utils.vertex_env.assert_project_agreement@4362a18865
  - cosa.utils.vertex_env.assert_region_is_certified@99a2a47b24
  - cosa.utils.vertex_env.assert_region_oracle_is_admissible@51354987aa
  - cosa.utils.vertex_env.assert_server_env_is_vertex_free@40e54fa17e
  - cosa.utils.vertex_env.compose_vertex_env@bd9e159c46
  - cosa.utils.vertex_env.format_dry_run@c452d8f413
  - cosa.utils.vertex_env.pane_guard@f401d7832e
  - cosa.utils.vertex_env.pane_unset_keys@c29a2b0fac
  - cosa.utils.vertex_env.parse_tmux_global_env@5ec54ce317
---
# Vertex environment guards

`cosa.utils.vertex_env` builds the environment for a Vertex-billed Claude Code session and refuses to launch when it could bill the wrong place. Only `src/scripts/start-cc-with-tmux.sh` and tests call it.

## What it does
- `compose_vertex_env( env=None, project_id=None, region=None )` returns `CLAUDE_CODE_USE_VERTEX=1`, `CLOUD_ML_REGION`, `ANTHROPIC_VERTEX_PROJECT_ID` and three model pins. Project and region default from `LUPIN_GCP_PROJECT_ID` and `LUPIN_VERTEX_REGION`, with no other fallback.
- It runs `assert_region_is_certified`, `assert_no_hostile_env`, `assert_project_agreement`, `assert_model_pin_agreement`. Each raises `VertexEnvError`, a `RuntimeError`.
- Only region `global` is certified, by a `rawPredict` that returned 200. `assert_region_oracle_is_admissible` and `assert_certifications_are_provenanced` guard that table, and the second runs at import.
- `assert_no_hostile_env` names every offender among the per-model region overrides, `GOOGLE_APPLICATION_CREDENTIALS`, `ANTHROPIC_VERTEX_BASE_URL` and `CLAUDE_CODE_SKIP_VERTEX_AUTH`.
- `assert_project_agreement` refuses a different `GOOGLE_CLOUD_PROJECT` or `GCLOUD_PROJECT`. `assert_model_pin_agreement` checks `ANTHROPIC_MODEL` and `ANTHROPIC_SMALL_FAST_MODEL`.
- `pane_unset_keys( vertex_path )` returns the keys the pane must unset. `pane_guard( env=None, vertex_path=False )` refuses if one survived, and on the Vertex path checks the session keys, region and pins.
- `parse_tmux_global_env( text )` parses `tmux show-environment -g`. A `-KEY` line is skipped and any other malformed line raises.
- `assert_server_env_is_vertex_free` refuses a tainted tmux server and prints `tmux set-environment -g -u <KEY>`. `format_dry_run( composed )` returns sorted `KEY=VALUE` lines.

## Don't
- Don't certify a region from the OpenAI-compatible endpoint or the publisher-model metadata call. Both answer 200 for a region that cannot serve.

## Invariants
- The guards read only the mapping they are given. A tainted tmux server blocks every launch on its socket, Max launches included.
- The pins are `claude-opus-4-8`, `claude-sonnet-4-6` and `claude-haiku-4-5@20251001`.
