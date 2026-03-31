# Theme Integration — Implementation Plan

**Date**: 2026-03-30
**Phase**: 11
**Scope**: Cross-renderer prompt tuning + theme color/font cascade into all visual renderers
**Effort**: 1 session
**Cost**: N/A (infrastructure only)
**Prerequisites**: Phases 9A, 9B, 10A, 10B complete

---

## Context

Each renderer generates visuals independently, but a polished presentation has visual consistency: charts match the slide color palette, D2 diagrams use complementary themes, generated images align with the overall aesthetic, and video clips feel cohesive.

This phase wires the existing theme system (YAML theme files + INI config) into all renderer prompts so that visual output is style-consistent across the entire deck.

---

## What We're Building

### Part A: Theme Color Extraction
Extract color palette and font choices from the loaded theme config into a format renderers can consume.

### Part B: Prompt Injection Layer
Each renderer's prompt module gets a `inject_theme_context()` function that appends theme-aware style directives.

### Part C: Per-Renderer Theme Mapping

| Renderer | Theme Integration |
|----------|------------------|
| Matplotlib | Inject color palette as rcParams overrides; font family from theme |
| D2 | Map presentation theme → D2 theme ID; custom color overrides |
| Nano Banana | Append color palette + style keywords to image prompt |
| Veo | Append mood/atmosphere keywords derived from theme |
| Mermaid | Inject theme colors into Mermaid `%%{init}` configuration |

### Part D: Orchestrator — Theme Context Propagation
Pass `theme_colors` and `theme_fonts` in kwargs to all renderers via `_render_visuals_async()`.

### Part E: Unit Tests
~15 tests covering theme extraction, prompt injection, per-renderer theme mapping.

---

## Detailed Implementation

### Part A: Theme Color Extraction

In orchestrator, after loading theme config:

```python
theme_context = {
    "primary"         : theme_config.get( "colors", {} ).get( "primary", "#2563EB" ),
    "secondary"       : theme_config.get( "colors", {} ).get( "secondary", "#1E40AF" ),
    "accent"          : theme_config.get( "colors", {} ).get( "accent", "#F59E0B" ),
    "background"      : theme_config.get( "colors", {} ).get( "background", "#FFFFFF" ),
    "text"            : theme_config.get( "colors", {} ).get( "text", "#1F2937" ),
    "heading_font"    : theme_config.get( "fonts", {} ).get( "heading", "Inter" ),
    "body_font"       : theme_config.get( "fonts", {} ).get( "body", "Inter" ),
    "code_font"       : theme_config.get( "fonts", {} ).get( "code", "JetBrains Mono" ),
    "theme_name"      : theme_config.get( "name", "default" ),
    "dark_mode"       : theme_config.get( "marp_class", "" ) == "invert",
}
```

### Part B: Per-Renderer Prompt Injection

**Matplotlib** (`prompts/matplotlib.py`):
```python
def inject_theme_context( prompt, theme_context ):
    colors = [ theme_context[ "primary" ], theme_context[ "secondary" ], theme_context[ "accent" ] ]
    return prompt + f"\n\nStyle requirements:\n- Color palette: {colors}\n- Font: {theme_context[ 'body_font' ]}\n- Background: {'dark' if theme_context[ 'dark_mode' ] else 'white'}"
```

**D2** (`prompts/d2.py`):
- Map theme to D2 theme ID: default→0, dark→3, minimal→1, sketch→100

**Nano Banana** (`prompts/image_gen.py`):
- Append: "Color palette: {primary}, {secondary}, {accent}. Style: professional, clean."

**Veo** (`prompts/video_gen.py`):
- Append: "Mood: {'dark and atmospheric' if dark_mode else 'bright and professional'}. Color tones: {primary} and {secondary}."

**Mermaid** (`prompts/visual.py`):
- Prepend `%%{init: {'theme': 'base', 'themeVariables': {'primaryColor': '{primary}'}}}%%` to generated Mermaid code

### Part C: Orchestrator Propagation

In `_render_visuals_async()`, pass theme context to all renderers:

```python
rendered = await renderer.render(
    visual_type      = visual_type,
    visual_description = visual_desc,
    api_client       = self.api_client if not self.dry_run else None,
    slide_title      = slide_title,
    output_dir       = visuals_dir,
    slide_index      = i,
    theme_context    = theme_context,  # NEW
)
```

---

## New/Modified Files

| Action | File | Change |
|--------|------|--------|
| **Modify** | `src/cosa/agents/presentation_generator/orchestrator.py` | Extract theme_context, pass in kwargs |
| **Modify** | `src/cosa/agents/presentation_generator/prompts/matplotlib.py` | Add `inject_theme_context()` |
| **Modify** | `src/cosa/agents/presentation_generator/prompts/d2.py` | Add `inject_theme_context()` |
| **Modify** | `src/cosa/agents/presentation_generator/prompts/image_gen.py` | Add `inject_theme_context()` |
| **Modify** | `src/cosa/agents/presentation_generator/prompts/video_gen.py` | Add `inject_theme_context()` |
| **Modify** | `src/cosa/agents/presentation_generator/prompts/visual.py` | Add Mermaid theme init block |
| **Create** | `src/tests/unit/test_presentation_theme_integration.py` | ~100 lines |

## Unit Tests (~15 tests)

| Class | Tests |
|-------|-------|
| `TestThemeExtraction` | full theme, partial theme, missing keys → defaults |
| `TestMatplotlibTheme` | color injection, dark mode, font override |
| `TestD2ThemeMapping` | default→0, dark→3, theme name→ID |
| `TestNanoBananaTheme` | color palette in prompt, style keywords |
| `TestVeoTheme` | mood keywords, color tone injection |
| `TestMermaidTheme` | init block prepended, color variables |

## Verification

1. Generate presentation with default theme → verify all visuals use blue/amber palette
2. Generate with dark theme → verify D2 uses theme 3, Matplotlib has dark background
3. Unit tests pass
4. Visual inspection: charts, diagrams, images, videos feel cohesive

## Open Questions

1. **Theme granularity**: How many colors to pass? Just primary/secondary/accent, or full palette?
2. **Mermaid backward compat**: Adding `%%{init}` block may break existing Mermaid output. Test carefully.
3. **Font availability**: Matplotlib may not have "Inter" installed. Fall back to system sans-serif?
