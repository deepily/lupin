---
capability: presentation-prompts
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.agents.presentation_generator.prompts.d2.get_d2_prompt@fe20572f4a
  - cosa.agents.presentation_generator.prompts.elaboration.get_elaboration_prompt@6f1eeedadc
  - cosa.agents.presentation_generator.prompts.elaboration.parse_elaboration_response@3119925d57
  - cosa.agents.presentation_generator.prompts.elaboration.summarize_timing_clamps@8f1ea99ec4
  - cosa.agents.presentation_generator.prompts.image_gen.get_image_prompt@8ed8acd98c
  - cosa.agents.presentation_generator.prompts.matplotlib.get_matplotlib_prompt@68b035c8c8
  - cosa.agents.presentation_generator.prompts.narrative.extract_narrative_metadata@38a73aa643
  - cosa.agents.presentation_generator.prompts.narrative.get_narrative_analysis_prompt@747e2ea7cc
  - cosa.agents.presentation_generator.prompts.narrative.parse_analysis_response@e348eef09e
  - cosa.agents.presentation_generator.prompts.outline.extract_outline_metadata@92f95da27d
  - cosa.agents.presentation_generator.prompts.outline.get_outline_prompt@8b2a0628c0
  - cosa.agents.presentation_generator.prompts.outline.parse_outline_response@8814198d85
  - cosa.agents.presentation_generator.prompts.video_gen.get_video_duration@22c9fbeec7
  - cosa.agents.presentation_generator.prompts.video_gen.get_video_prompt@f877ff68c3
  - cosa.agents.presentation_generator.prompts.visual.get_mermaid_prompt@ede42d1ecc
  - cosa.agents.presentation_generator.prompts.visual.build_visual_prompt@546a059828
---
# Presentation prompt builders

Each `prompts/*.py` function builds the user message for one model call in [[presentation-generation]] or [[presentation-visual-renderers]], and some parse the reply. They send nothing.

## What it does
- `get_narrative_analysis_prompt` builds the analysis request from the source, its sections, the target duration and a slide budget. The budget comes from the orchestrator when given. Audience guidance and revision feedback are optional.
- `get_outline_prompt` allocates the budget as 2 opening slides, 3 closing slides and the rest for the body. It lists the narrative sections and asks for assertion-style titles. Revision feedback is appended.
- `get_elaboration_prompt` lists the outlines, the average seconds per slide and the source text. The source is clipped to `max_source_chars` with a note.
- `parse_analysis_response`, `parse_outline_response` and `parse_elaboration_response` recover the JSON object and return a non-empty list. They raise `ValueError` when it is missing, has no list under `sections`, `outline` or `slides`, or has no dict entries. Unknown arc positions, slide types and visual types are reset to defaults with a warning.
- `parse_elaboration_response` clamps `timing_seconds` to 15 to 180, uses 60 when missing, and keeps the raw value. It logs a warning if any slide was clamped.
- `summarize_timing_clamps( slides )` returns the slide count, clamped count, raw and clamped totals, the largest overshoot and the clamped slides. Slides with no raw value are left out.
- `extract_narrative_metadata` and `extract_outline_metadata` read the totals and the assessment or coherence note after stripping a code fence, through the shared `extract_json_metadata`. They return `{}` when the text is not valid JSON.
- `get_mermaid_prompt`, `get_d2_prompt` and `get_matplotlib_prompt` ask for code only, with a type suggested from keywords in the description. All three call `build_visual_prompt`: the optional title, the visual type, the hint, the description and the instruction, one per line.
- `get_image_prompt` adds a style per visual type, a 16:9 hint and a no-text rule for hero images, backgrounds and icons.
- `get_video_prompt` builds a Veo prompt. `get_video_duration` returns 5, 6 or 8 seconds by type and 8 for an unknown type.
