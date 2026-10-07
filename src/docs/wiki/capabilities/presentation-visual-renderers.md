---
capability: presentation-visual-renderers
pin_algorithm: py3.13.xf75af6/ts5.9.3
pins:
  - cosa.agents.presentation_generator.renderers.visual_registry.VisualRenderer@bc1d480c23
  - cosa.agents.presentation_generator.renderers.visual_registry.VisualRendererRegistry@36a7db9119
  - cosa.agents.presentation_generator.renderers.mermaid.MermaidRenderer@09cc6bafec
  - cosa.agents.presentation_generator.renderers.matplotlib_renderer.MatplotlibRenderer@c124ca14ce
  - cosa.agents.presentation_generator.renderers.d2_renderer.D2Renderer@33b2e925bc
  - cosa.agents.presentation_generator.renderers.nano_banana.NanoBananaRenderer@c9d573383b
  - cosa.agents.presentation_generator.renderers.veo_renderer.VeoRenderer@dda275290e
  - cosa.agents.presentation_generator.renderers.placeholder.PlaceholderRenderer@e1854f7122
  - cosa.agents.presentation_generator.gemini_client.GeminiImageClient@3c8ea0316a
  - cosa.agents.presentation_generator.renderers.pptx_deck_renderer.PptxDeckRenderer@271c30f54f
---
# Presentation visual renderers

Phase 7 of [[presentation-generation]] finds each `<!-- VISUAL: type | description -->` marker in the Marp file and replaces it with content from one renderer chosen by `type`. A renderer returns Marp-ready text, or `None` on failure.

## What it does
- `VisualRendererRegistry.get( type )` always returns a renderer; an unregistered type gets `PlaceholderRenderer`, a visible TODO block. A renderer that returns `None` is also replaced by a placeholder.
- Types: `diagram` is `MermaidRenderer` (a fenced mermaid block). `chart`, `plot`, `graph`, `data_viz` are `MatplotlibRenderer` (PNG). `flowchart_d2`, `architecture` are `D2Renderer` (SVG). `hero_image`, `infographic`, `title_background`, `icon`, `before_after`, `icon_only` are `NanoBananaRenderer`. `title_video`, `flow_animation`, `process_video` are `VeoRenderer`. `screenshot` is the placeholder.
- The first three ask Claude for diagram or plotting code through `PresentationAPIClient` ([[generator-sdk-clients]]). Files go to `visuals/` beside the Marp file and are linked by relative path.
- `NanoBananaRenderer` and `VeoRenderer` share one `GeminiImageClient`. `PptxDeckRenderer` later builds the `.pptx` with python-pptx and embeds the PNGs.

## Invariants
- Phase 7 is not fatal: an exception inside it leaves the markers in the Marp file and the run continues.
- With `offline_mode`, no renderer is registered and every type is a placeholder. If the Gemini import or client construction fails, those types are unregistered and fall back the same way; a missing key at `src/conf/keys/gemini` makes `generate_image` return `False`, so the renderer returns `None` and the placeholder is used.
- `MatplotlibRenderer` runs the generated code in a separate `python3` process with a 30-second timeout and the system temp directory as its working directory. It inherits the environment and has no other restriction. `D2Renderer` needs the `d2` program on `PATH` and gives up after 30 seconds.
- `GeminiImageClient` budgets per presentation: 1.00 for images (0.067 each) and 5.00 for video (0.20 a second); past the limit it returns `False` and the type falls back. Every image call prints a loud notice to stderr.
- `VeoRenderer` writes an MP4. It adds a still-frame `<img>` inside the `<video>` tag only if `ffmpeg` is on `PATH` and the extraction (15-second timeout) leaves the frame file; otherwise the tag holds no image. A deck gets at most `max_videos` (default 5, which the orchestrator keeps): the sixth returns `None` and falls back to a placeholder.
- `PptxDeckRenderer` embeds raster images only: d2 SVGs and mermaid blocks are a known gap, and those slides keep their text.

## How to extend
- Subclass `VisualRenderer`, set `SUPPORTED_TYPES`, return `None` on failure, and register it in `_build_visual_registry` in the orchestrator.

## Don't
- Don't switch `GeminiImageClient` to Vertex: the API-key path is a recorded exception, and Imagen answered 404 on the GCP project at the 2026-08-25 measurement.
