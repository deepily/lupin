---
capability: podcast-script-types
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.agents.podcast_generator.script_types.ScriptTypeProfile@0a95e8fc95
  - cosa.agents.podcast_generator.script_types.get_profile@dba44bd84b
  - cosa.agents.podcast_generator.script_types.validate_review@99a65763a1
  - cosa.agents.podcast_generator.script_types.effective_review@3dc5e36c63
  - cosa.agents.podcast_generator.script_types.apply_script_type@176ccc6a37
  - cosa.agents.podcast_generator.script_types.resolve_podcast_config@2e4fb69ec1
  - cosa.agents.podcast_generator.orchestrator.one_shot_notice@34aef7462e
  - cosa.agents.podcast_generator.prompts.status_report.get_status_analysis_prompt@23f1326503
  - cosa.agents.podcast_generator.prompts.status_report.get_status_script_prompt@76236e6eac
  - cosa.agents.podcast_generator.state.DigestItem@e4dfb2b7b9
  - cosa.agents.podcast_generator.state.StatusDigest@77a13fb494
  - cosa.agents.podcast_generator.state.StatusDigest.all_items@7e9285cc20
  - cosa.agents.podcast_generator.state.StatusDigest.key_subtopics@abfd6eee00
  - cosa.agents.podcast_generator.state.StatusDigest.unsupported_items@40ba8e153d
  - cosa.agents.podcast_generator.translation_check.spanish_stopword_ratio@ffd8da8981
---
# Podcast script types

A script type is a frozen profile in `script_types.py`: prompts, length, analysis kind and a default review mode. The two types are `research_critical` (the default) and `status_report`. The run itself is in [[podcast-generation]].

## What it does
- `get_profile( name )` returns the profile; `None` means `research_critical`. An unknown name raises `ValueError` that lists the valid ones.
- `validate_review` accepts `None`, `ask` or `one_shot`. `effective_review( config )` is the config's own review, else the profile's default.
- `research_critical` defaults to `ask`. `status_report` defaults to `one_shot`, which stops for no review and asks nobody anything.
- `apply_script_type` sets the type and a concrete review on a config. Precedence is request, then profile, then INI. `resolve_podcast_config` builds the config from the INI first.
- `status_report` reads its own INI keys for duration, exchanges and audience (`podcast status report *`). Research uses the generic podcast keys.
- A status report is analysed into a `StatusDigest` of `DigestItem` rows, each with the source line it came from. `unsupported_items( text )` lists items whose line is not in the document.
- `get_status_analysis_prompt` and `get_status_script_prompt` build the two status prompts; `max_source_chars` clips the document, and both prompts use the shared `clip_to_ceiling` and `audience_block` of [[podcast-prompts]].
- `one_shot_notice( True )` is the completion sentence saying nobody read the script. It is `""` otherwise.
- `spanish_stopword_ratio( text )` is the share of Spanish function words, 0.0 for no words. A Spanish script under `podcast translation min spanish stopword ratio` (0.20) fails as untranslated.

## Don't
- Don't use `one_shot` with review-only mode: it raises `ValueError`, since that mode exists only to review.
