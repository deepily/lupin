---
capability: presentation-deck-model
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.agents.presentation_generator.deck_verdict.DeckVerdict@498721a677
  - cosa.agents.presentation_generator.renderers.marp_text_renderer.MarpTextRenderer@f029f1e4f4
  - cosa.agents.presentation_generator.state.ArcPosition@b01b389b6c
  - cosa.agents.presentation_generator.state.NarrativeSection@8f2653b848
  - cosa.agents.presentation_generator.state.PresenterNotes@8e1997eb25
  - cosa.agents.presentation_generator.state.SlideModel@b63625d45e
  - cosa.agents.presentation_generator.state.SlideOutline@497cec2ce0
  - cosa.agents.presentation_generator.state.create_initial_state@ce784add80
---
# Presentation deck model and verdict

The data shapes and two output checkers for [[presentation-generation]]. `PresentationModel` and `verify_presentation_deck` are on that page; the rest of `state.py`, the Marp text renderer and `DeckVerdict` are here.

## What it does
- `ArcPosition` is a string enum with six values: setup, argument, evidence, transition, conclusion and cta.
- `NarrativeSection` is one classified part of the source: heading, content, an arc position and a proposed slide count (default 1).
- `SlideOutline` is the light entry from the outline step. It has a number, an arc position (`opening`, `body` or `closing`), a slide type, a title, a visual type and an optional source hint.
- `SlideModel` is the full slide: those fields plus subtitle, visual description, bullets and `presenter_notes`.
- `PresenterNotes` holds the transition, talking points, emphasis and `timing_seconds` (default 60). `timing_seconds_raw` keeps the model's value before the clamp, and is `None` when the model gave none.
- `create_initial_state( source_path, user_id )` returns the orchestrator's tracking dict with every phase key `None` or zero.
- `MarpTextRenderer.render( presentation, theme_config )` returns Marp Markdown: front matter, then slides separated by `---`. Every method is static.
- Per slide it adds a `<!-- VISUAL: type | description -->` marker unless the visual type is `text_only`, then the presenter notes as a comment. An unknown slide type is rendered like a content slide.
- `DeckVerdict` is the result of `verify_presentation_deck`. It is truthy only when `passed` is set, and carries a reason, path, size, slide count and text-run count.

## Invariants
- The verdict reads the real file. A deck whose slides hold only images fails the default text-run check, because notes text is not counted.
