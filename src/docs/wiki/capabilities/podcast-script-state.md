---
capability: podcast-script-state
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.agents.podcast_generator.orchestrator.build_auto_continue_disclosure@2417ee8502
  - cosa.agents.podcast_generator.state.ContentAnalysis@866c21b049
  - cosa.agents.podcast_generator.state.OrchestratorState@9364843404
  - cosa.agents.podcast_generator.state.PodcastMetadata@3be7d368cd
  - cosa.agents.podcast_generator.state.PodcastState@023d8ca4b9
  - cosa.agents.podcast_generator.state.ProsodyAnnotation@0071593b5b
  - cosa.agents.podcast_generator.state.ScriptSegment@9b17585b17
  - cosa.agents.podcast_generator.state.create_initial_state@7777631492
  - cosa.agents.podcast_generator.state.extract_prosody_markers@7d478bede1
  - cosa.agents.podcast_generator.state.validate_prosody_preservation@0e6ee10b7a
---
# Podcast script state

`state.py` holds the data shapes the podcast orchestrator passes between phases. `PodcastScript` is described in [[podcast-generation]]. It carries `script_type`, which `to_markdown( include_script_type=True )` saves as a `## Script Type:` line. This page covers the rest of the module and the review-gate wording.

## What it does
- `OrchestratorState` is the phase enum with ten values: five working phases from `LOADING_RESEARCH` to `STITCHING_AUDIO`, `WAITING_SCRIPT_REVIEW`, `COMPLETED`, `FAILED`, `PAUSED` and `STOPPED`.
- `PodcastState` is a typed dict with the whole run. Its `content_analysis` is a `ContentAnalysis` or a `StatusDigest` ([[podcast-script-types]]). It also holds input paths, the draft script, approval, feedback, revision count, audio paths, `metadata` and `current_state`. `create_initial_state( research_doc_path, user_id )` fills it with `LOADING_RESEARCH`, zero counters and empty lists.
- `ContentAnalysis` is the analysis result: main topic, subtopics, facts, questions, analogies, an inferred audience, a complexity level and an estimated length. `PodcastMetadata` records ids, paths, call counts, tokens and an estimated cost.
- `ScriptSegment` is one turn: speaker, role (`curious` or `expert`), text and an optional topic. `to_markdown()` returns `**[Speaker - Role]**: text`.
- `ProsodyAnnotation` lists 13 marker names. `extract_prosody_markers( text )` returns the lowercased names of every `*[name]*` marker in the text, in order, and `[]` for `None`.
- `validate_prosody_preservation( english, translated )` compares the marker names found in the text of each script. It returns `( preserved, details )`; it fails if a name is missing or extra. Counts may differ.
- `build_auto_continue_disclosure( timeout_seconds )` returns the sentence added to the script-review question: the wait in whole minutes (at least 1) and that silence continues the run. It raises `ValueError` unless the timeout is a positive int.

## Don't
- Don't count markers from the `prosody` list of a segment. The translation path leaves it empty; read the text.
