---
capability: preference-replay-one-time-rescore
pin_algorithm: py3.13.xaad549/ts5.9.3
pins:
  - cosa.research.preference_replay.replay_loop.complete_action_summary@f38d9832d6
  - cosa.research.preference_replay.one_time_rescore.read_switches@d54c31e172
  - cosa.research.preference_replay.one_time_rescore.read_answers@a370183181
  - cosa.research.preference_replay.one_time_rescore.score_ask@c9bd7cf110
  - cosa.research.preference_replay.one_time_rescore.score_arm@f056034779
  - cosa.research.preference_replay.one_time_rescore.tally@097381c90f
  - cosa.research.preference_replay.one_time_rescore.paired@d1d6b4ee1b
  - cosa.research.preference_replay.one_time_rescore.rescore@9720489977
  - cosa.research.preference_replay.one_time_rescore.load_per_ask@1d62937b33
  - cosa.research.preference_replay.one_time_rescore.build_report@e89d8becac
  - cosa.research.preference_replay.one_time_rescore.render_markdown@e7f69b5e4d
  - cosa.research.preference_replay.one_time_rescore.main@344eda0f73
---
# Preference replay: the one-time re-score

Re-scores the five context arms' stored forecasts under the complete-action measure ([[preference-replay-context-arms]]). It makes no model call and recomputes no forecast.

## Inputs
- `load_per_ask( per_ask_dir )` reads the five committed per-ask files. It raises `ValueError` when the arms did not score the same ids in the same order.
- `read_answers( session )` reads each ask's full answer and schema in a read-only transaction. `read_switches( ini_path )` reads the prediction switches.

## Scoring
- `score_ask( record, answer )` returns `old`, `new` and `decided`. `new` is None when only the judge could decide. An abstention is False and decided. `score_arm` keys these by ask id.
- `tally( scores, kind )` counts old correct, new passed, decided and undecided, with coverage. An undecided ask never counts as passed.
- `paired( arm, base, column )` pairs an arm with a baseline and returns the difference and the exact McNemar p.
- `rescore( per_arm, answers )` pairs each arm with Q and, on yes/no asks, with always-yes. It flags `sign_reversed` and `population_effect`.

## Report
- `build_report` adds provenance, the switches and the phases that stored no forecasts. It lists each sign reversal as a finding, not an action.
- `render_markdown` lays it out, and `main` writes a Markdown and a JSON file. It refuses an output directory under `src/rnd`.
- `complete_action_summary( run, arm )` in the replay loop gives an arm's `coverage`, `pass_rate` and `complete_action_accuracy`.
