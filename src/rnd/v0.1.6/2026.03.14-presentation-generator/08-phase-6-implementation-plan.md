# Presentation Generator Phase 6: Marp Text Rendering — Implementation Plan

**Date**: 2026-03-28
**Plan source**: `~/.claude/plans/mutable-marinating-alpaca.md`
**Scope**: YAML-to-Marp text rendering, theme system, orchestrator integration, unit tests
**MVP**: MVP-2 (Text Rendering)

---

## Context

Phases 1-5 of the Presentation Generator are complete (Sessions 367-374). The pipeline ingests a source document, calls Claude to analyze its narrative structure, generates slide outlines, elaborates full content with presenter notes, and serializes everything to a `PresentationModel` YAML intermediate file. The YAML file is the contract between content generation and rendering — Phase 6 is the first consumer of that contract.

**Phase 6 is pure text transformation**: no LLM calls, no network I/O, no voice gates. It reads a `PresentationModel` (populated by Phase 5 or loaded from YAML) and emits a Marp Markdown file that can be opened directly in Marp (VS Code extension, marp-cli, or marp.app) to produce a slide deck with presenter notes.

**Why Marp?** (Decision from `01-strategy-and-design.md` Section 2.4):
- Markdown syntax — editable in any text editor
- Exports natively to PDF, PPTX, and HTML via `marp-cli`
- Built-in presenter notes, syntax highlighting, and themes
- YAML frontmatter for per-deck configuration
- CSS-based theming with full layout control

---

## What We're Building

### Part A: Theme System (Data Layer)

Create the default theme YAML file that defines how a Marp presentation looks. The theme schema was specified in `01-strategy-and-design.md` Section 3.2. This is a **data file** consumed by the renderer — no code.

### Part B: Marp Text Renderer (Core Logic)

A stateless renderer class that transforms `PresentationModel` + theme config into a valid Marp Markdown string. Pure function: model in, string out.

### Part C: Orchestrator Integration

Replace the `_render_text_async` stub with real implementation that loads a theme, calls the renderer, writes the output file, and stores the path for the job to read.

### Part D: Unit Tests

Comprehensive tests for the renderer covering all slide types, presenter notes formatting, frontmatter generation, theme application, edge cases, and orchestrator integration.

---

## Detailed Implementation

### Part A: Theme System

**A.1 — Create default theme file**

File: `src/cosa/agents/presentation_generator/templates/themes/default.yaml` (new)

Schema from strategy doc Section 3.2, adapted for Marp rendering:

```yaml
theme:
  name: "default"
  description: "Clean, professional default theme"
  marp_theme: "default"      # Built-in Marp theme base
  marp_class: ""             # No global class override

  colors:
    primary: "#2563EB"       # Blue — headings, emphasis
    secondary: "#1E40AF"     # Dark blue — subtitles
    accent: "#F59E0B"        # Amber — callouts, highlights
    background: "#FFFFFF"    # White background
    text: "#1F2937"          # Dark gray text
    code_background: "#F3F4F6"  # Light gray for code blocks

  fonts:
    heading: "Inter"
    body: "Inter"
    code: "JetBrains Mono"

  layout:
    title_alignment: "center"   # Title slide: center | left
    bullet_style: "dash"        # Bullet character: dash | disc | none
    code_block_theme: "github"  # Syntax highlight theme
    paginate: true              # Show page numbers
    header_template: ""         # Marp header (empty = none)
    footer_template: "{speaker} | {date}"  # Marp footer with interpolation

  branding:
    logo_path: null
    logo_position: "bottom-right"
    footer_text: null
    watermark: null
```

**Design notes**:
- `marp_theme` maps to Marp's built-in `theme` directive (default, gaia, uncover)
- `marp_class` maps to Marp's `class` directive (e.g., "invert" for dark mode)
- `header_template` / `footer_template` support `{title}`, `{speaker}`, `{date}` placeholders interpolated at render time from `PresentationModel` fields
- `paginate` maps directly to Marp's `paginate` frontmatter directive
- CSS is generated from the color/font/layout settings, not stored as raw CSS in the YAML

---

### Part B: Marp Text Renderer

**B.1 — Create `MarpTextRenderer` class**

File: `src/cosa/agents/presentation_generator/renderers/marp_text_renderer.py` (new, ~250 lines)

**Class design**: All `@staticmethod` methods — no constructor, no instance state. The renderer is a pure function namespace.

```
MarpTextRenderer
    render( presentation: PresentationModel, theme_config: dict ) -> str
    _render_frontmatter( presentation, theme_config ) -> str
    _render_title_slide( slide: SlideModel, presentation: PresentationModel ) -> str
    _render_content_slide( slide: SlideModel ) -> str
    _render_section_divider_slide( slide: SlideModel ) -> str
    _render_conclusion_slide( slide: SlideModel ) -> str
    _render_slide( slide: SlideModel, presentation: PresentationModel ) -> str
    _render_presenter_notes( notes: PresenterNotes ) -> str
    _render_visual_placeholder( slide: SlideModel ) -> str
    _generate_css( theme_config: dict ) -> str
    _interpolate_template( template: str, presentation: PresentationModel ) -> str
```

**B.2 — `render()` main method**

The top-level entry point. Assembles the full Marp document:

1. Render frontmatter block (YAML between `---` delimiters)
2. Render title slide (first slide, always slide #1)
3. For each remaining slide: render `---` separator + slide content + presenter notes
4. Join all sections with double newlines
5. Return complete Marp markdown string

**B.3 — `_render_frontmatter()` — Marp YAML header**

Generates the YAML frontmatter that Marp reads for deck-level configuration:

```markdown
---
marp: true
theme: {marp_theme}
class: {marp_class}
paginate: {paginate}
header: "{interpolated_header}"
footer: "{interpolated_footer}"
style: |
  {generated_css}
---
```

Details:
- `marp: true` is always present (identifies the file as Marp)
- `theme` from `theme_config["theme"]["marp_theme"]`
- `class` only emitted if non-empty
- `paginate` from `theme_config["theme"]["layout"]["paginate"]`
- `header` / `footer` interpolated with `{title}`, `{speaker}`, `{date}` from `PresentationModel`
- `style` block generated from color/font settings via `_generate_css()`

**B.4 — `_generate_css()` — Theme CSS from config**

Converts theme color/font/layout settings into Marp CSS:

```css
section {
  font-family: {body_font}, sans-serif;
  color: {text_color};
  background-color: {background_color};
}
h1, h2, h3 {
  font-family: {heading_font}, sans-serif;
  color: {primary_color};
}
h2 {
  color: {secondary_color};
}
code {
  font-family: {code_font}, monospace;
  background-color: {code_background_color};
}
em {
  color: {accent_color};
}
```

Keep it minimal — Marp's built-in themes handle most layout. We only override colors and fonts.

**B.5 — `_render_slide()` — Type dispatcher**

Routes each slide to the appropriate render method based on `slide.type`:

| `slide.type` | Render Method | Notes |
|--------------|---------------|-------|
| `title` | `_render_title_slide()` | Opening title with subtitle + speaker/date |
| `content`, `key_point`, `evidence`, `hook`, `agenda` | `_render_content_slide()` | Standard bullet slide |
| `section_divider` | `_render_section_divider_slide()` | Full-page centered heading (Marp `_class: lead`) |
| `conclusion`, `summary`, `cta`, `qa` | `_render_conclusion_slide()` | Bullets + optional CTA emphasis |
| *unknown type* | `_render_content_slide()` | Safe fallback — any type renders as bullets |

**B.6 — Slide rendering methods**

**Title slide** (`_render_title_slide`):
```markdown
<!-- _class: lead -->
<!-- _paginate: skip -->

# {title}
## {subtitle}

{speaker} | {date}
```
- Uses Marp `_class: lead` for centered layout
- Skips pagination on title slide
- Subtitle only rendered if not None/empty
- Speaker/date line only rendered if either is non-empty on PresentationModel

**Content slide** (`_render_content_slide`):
```markdown
# {title}

- {bullet_1}
- {bullet_2}
- {bullet_3}
```
- Subtitle rendered as `## {subtitle}` if present
- Bullets use `- ` prefix (dash style per theme — though Marp renders markdown lists natively)
- Visual placeholder appended if `visual_type != "text_only"` (Phase 7 will replace)
- Presenter notes appended as HTML comment

**Section divider** (`_render_section_divider_slide`):
```markdown
<!-- _class: lead -->

# {title}
```
- Full-page centered heading using Marp's `lead` class
- No bullets, no subtitle typically
- Minimal presenter notes (transition only)

**Conclusion slide** (`_render_conclusion_slide`):
```markdown
# {title}

- {bullet_1}
- {bullet_2}
- {bullet_3}
```
- Same structure as content slide
- Emphasis from presenter notes can be surfaced as a visual callout (`> {emphasis}`) if present — **design decision**: keep this simple for MVP, just render as standard bullets. The emphasis lives in presenter notes where it belongs.

**B.7 — `_render_presenter_notes()` — HTML comment block**

Marp uses HTML comments for presenter notes (visible in presenter view, hidden from audience):

```markdown
<!--
Transition: So we've seen the problem -- now let's look at what we built.

Talking points:
- Explain the three cache layers left-to-right
- Emphasize L1 handles 80% -- this is the key insight
- Mention the fallback chain is automatic

Timing: 75s
Emphasis: The 80% L1 hit rate -- pause here, let it sink in
-->
```

Rules:
- Only emit fields that are not None/empty
- `talking_points` rendered as bullet list within the comment
- `timing_seconds` rendered as `Timing: {n}s`
- If notes has no substantive content (empty talking_points, None transition, None emphasis), emit empty comment or skip
- **Reuse**: The format matches the presenter notes example from `01-strategy-and-design.md` Section 1.5

**B.8 — `_render_visual_placeholder()` — Phase 7 hook**

For slides where `visual_type != "text_only"`, emit a placeholder that Phase 7 will replace:

```markdown
<!-- VISUAL: {visual_type} | {visual_description} -->
```

This is a structured comment that Phase 7's visual renderer can find and replace with actual Mermaid code blocks, images, or tables. The comment format is machine-parseable (Phase 7 can regex for `<!-- VISUAL: ... -->`).

If `visual_description` is None, emit:
```markdown
<!-- VISUAL: {visual_type} | (no description provided) -->
```

**B.9 — `_interpolate_template()` — Footer/header variable substitution**

Replace `{title}`, `{speaker}`, `{date}` in template strings with values from `PresentationModel`:

```python
template.replace( "{title}", presentation.title )
        .replace( "{speaker}", presentation.speaker )
        .replace( "{date}", presentation.date )
```

If a field is empty string, the placeholder is replaced with empty string (no error).

---

**B.10 — Update `renderers/__init__.py`**

File: `src/cosa/agents/presentation_generator/renderers/__init__.py` (modify)

Add re-export so the orchestrator can import cleanly:

```python
"""Visual and text renderers for Presentation Generator Agent."""

from .marp_text_renderer import MarpTextRenderer

__all__ = [ "MarpTextRenderer" ]
```

---

### Part C: Orchestrator Integration

**C.1 — Add `_load_theme_config()` static method**

File: `src/cosa/agents/presentation_generator/orchestrator.py` (add method)

```python
@staticmethod
def _load_theme_config( templates_path: str, theme_name: str, debug: bool = False ) -> dict:
```

Logic:
1. Build absolute path: `cu.get_project_root() + templates_path + theme_name + ".yaml"`
2. If file exists: load with `yaml.safe_load()`, return dict
3. If file missing: log warning, return hardcoded default dict matching the schema
4. If YAML parse error: log error, return hardcoded default dict

The hardcoded fallback ensures rendering never fails due to a missing theme file. It matches `default.yaml` exactly.

**C.2 — Add `_write_marp()` static method**

File: `src/cosa/agents/presentation_generator/orchestrator.py` (add method)

Follow the existing `_write_yaml` pattern exactly (lines 979-993):

```python
@staticmethod
def _write_marp( marp_path: str, marp_content: str ) -> None:
    """
    Write Marp Markdown content to disk, creating directories as needed.

    Requires:
        - marp_path is an absolute file path
        - marp_content is a non-empty string

    Ensures:
        - Parent directory exists
        - File is written with UTF-8 encoding
    """
    os.makedirs( os.path.dirname( marp_path ), exist_ok=True )
    with open( marp_path, "w", encoding="utf-8" ) as f:
        f.write( marp_content )
```

**C.3 — Replace `_render_text_async()` stub**

File: `src/cosa/agents/presentation_generator/orchestrator.py` (replace lines 995-1002)

Current stub:
```python
async def _render_text_async( self, presentation: Optional[ PresentationModel ] ) -> None:
    """Phase 6: Render YAML to Marp Markdown. TODO (Phase 6): Load theme, generate Marp markdown."""
    if self.debug: print( "[Orchestrator] Phase 6: Render Text (stub)" )
    await asyncio.sleep( 0.1 )
```

Replacement implementation:

```python
async def _render_text_async( self, presentation: Optional[ PresentationModel ] ) -> None:
    """
    Phase 6: Render PresentationModel to Marp Markdown file.

    Loads theme configuration, calls MarpTextRenderer to produce
    Marp-compatible markdown, and writes to disk alongside the YAML.

    Requires:
        - presentation is a valid PresentationModel (not None)
        - self.config has templates_path and default_theme set

    Ensures:
        - Marp markdown file written to config-defined output path
        - self._presentation_state["marp_path"] is set
        - File contains valid Marp frontmatter + slide separators
    """
    if presentation is None:
        logger.warning( "Phase 6: No presentation model — skipping text rendering" )
        return

    if self.debug: print( "[Orchestrator] Phase 6: Render Text — starting" )

    try:
        # Load theme configuration
        theme_config = self._load_theme_config(
            self.config.templates_path,
            self.config.default_theme,
            debug=self.debug
        )

        # Render Marp markdown (pure transformation, no I/O)
        from .renderers import MarpTextRenderer
        marp_content = MarpTextRenderer.render( presentation, theme_config )

        # Get output path (.md alongside .yaml)
        user_id   = self._presentation_state.get( "user_id", "unknown" )
        marp_path = self.config.get_output_path( user_id, presentation.title, file_type="md" )

        # Write to disk in thread pool (non-blocking)
        loop = asyncio.get_event_loop()
        await loop.run_in_executor( None, self._write_marp, marp_path, marp_content )

        # Store path for job to read
        self._presentation_state[ "marp_path" ] = marp_path

        if self.debug:
            file_size = len( marp_content.encode( "utf-8" ) )
            print( f"[Orchestrator] Marp written: {marp_path}" )
            print( f"[Orchestrator] Marp stats: {presentation.total_slides} slides, {file_size:,} bytes" )

        # Notify progress
        await voice_io.notify(
            f"Marp rendered: {presentation.total_slides} slides",
            priority="low"
        )

    except Exception as e:
        logger.error( f"Phase 6 failed: {e}", exc_info=True )
        await voice_io.notify(
            f"Marp rendering failed: {str( e )[ :100 ]}",
            priority="urgent"
        )
        # Don't re-raise — marp_path stays None, job can still complete with YAML only
```

**Design decision**: Phase 6 failure is non-fatal. If the renderer crashes, `marp_path` stays `None` and the job still delivers the YAML artifact. The job's completion abstract already handles `None` marp_path gracefully (shows `None` for the Marp link). This is consistent with the "content first, rendering second" philosophy.

**C.4 — Add import for `yaml` (if not already imported)**

Check if `import yaml` is already at the top of orchestrator.py. If not, add it to the imports section.

---

### Part D: Unit Tests

**D.1 — Create test file**

File: `src/tests/unit/test_presentation_marp_renderer.py` (new, ~350 lines)

**Fixtures**:

```python
@pytest.fixture
def sample_presentation():
    """Full PresentationModel with diverse slide types for rendering tests."""
    # 5 slides: title, content, section_divider, content with visual, conclusion
    ...

@pytest.fixture
def default_theme_config():
    """Theme config dict matching templates/themes/default.yaml."""
    ...

@pytest.fixture
def sample_slide_content():
    """Single content slide with all fields populated."""
    ...

@pytest.fixture
def sample_slide_title():
    """Title slide with subtitle and speaker."""
    ...
```

**Test classes and cases** (~20 tests):

```
class TestMarpFrontmatter:
    test_frontmatter_contains_marp_true          # "marp: true" in output
    test_frontmatter_theme_directive              # Theme from config applied
    test_frontmatter_paginate_directive           # paginate: true/false
    test_frontmatter_footer_interpolation         # {speaker} and {date} replaced
    test_frontmatter_empty_class_omitted          # No "class:" line when empty
    test_frontmatter_css_generated                # style: | block present with colors/fonts

class TestSlideRendering:
    test_title_slide_structure                    # # title, ## subtitle, speaker line
    test_title_slide_no_subtitle                  # Subtitle omitted when None
    test_title_slide_lead_class                   # <!-- _class: lead --> present
    test_content_slide_bullets                    # Bullet list rendered correctly
    test_content_slide_with_subtitle              # ## subtitle present
    test_section_divider_centered                 # lead class, no bullets
    test_conclusion_slide_bullets                 # Standard bullet rendering
    test_unknown_type_fallback                    # Unknown type → content-style

class TestPresenterNotes:
    test_notes_full_fields                        # All fields in HTML comment
    test_notes_omits_none_fields                  # None transition/emphasis skipped
    test_notes_empty_talking_points               # No bullet list when empty
    test_notes_timing_format                      # "Timing: 60s" format

class TestVisualPlaceholders:
    test_visual_placeholder_emitted               # VISUAL comment for non-text slides
    test_text_only_no_placeholder                 # No VISUAL comment for text_only
    test_visual_placeholder_no_description        # Fallback text when None

class TestFullRender:
    test_slide_separator_count                    # Number of "---" matches slide count
    test_round_trip_structure                     # Render full model, verify structure
    test_empty_presentation                       # 0 slides → frontmatter only
    test_single_slide                             # 1 slide → no separator after frontmatter's closing ---

class TestThemeLoading:
    test_load_existing_theme                      # default.yaml loads correctly
    test_missing_theme_fallback                   # Missing file → fallback dict
    test_theme_config_structure                   # Loaded dict has expected keys
```

**D.2 — Orchestrator integration tests**

Add to existing `src/tests/unit/test_presentation_generator_job.py` (~5 tests):

```
class TestPhase6Integration:
    test_render_text_sets_marp_path               # _presentation_state["marp_path"] is set
    test_render_text_creates_md_file              # .md file exists on disk
    test_render_text_none_presentation            # None input → no crash, path stays None
    test_render_text_file_content_valid           # Written file starts with "---\nmarp: true"
    test_marp_path_extension                      # Path ends with .md
```

---

## Implementation Order

| Step | Part | What | Dependencies |
|------|------|------|-------------|
| 0 | — | Serialize this plan to `src/rnd/` + update `00-index.md` | None |
| 1 | A.1 | Create `default.yaml` theme file | None |
| 2 | B.1-B.9 | Implement `MarpTextRenderer` class | A.1 (for schema reference) |
| 3 | B.10 | Update `renderers/__init__.py` | B.1 |
| 4 | D.1 | Write renderer unit tests | B.1 (test what we just built) |
| 5 | C.1-C.2 | Add `_load_theme_config()` + `_write_marp()` to orchestrator | A.1, B.1 |
| 6 | C.3-C.4 | Replace `_render_text_async()` stub | C.1, C.2, B.10 |
| 7 | D.2 | Write orchestrator integration tests | C.3 |
| 8 | — | Run full unit test suite — verify no regressions | All |

---

## Files Summary

| Action | File | Est. Lines |
|--------|------|-----------|
| **Create** | `src/cosa/agents/presentation_generator/templates/themes/default.yaml` | ~40 |
| **Create** | `src/cosa/agents/presentation_generator/renderers/marp_text_renderer.py` | ~250 |
| **Create** | `src/tests/unit/test_presentation_marp_renderer.py` | ~350 |
| **Modify** | `src/cosa/agents/presentation_generator/renderers/__init__.py` | +3 |
| **Modify** | `src/cosa/agents/presentation_generator/orchestrator.py` | +60 (replace stub + add 2 methods) |
| **Modify** | `src/tests/unit/test_presentation_generator_job.py` | +50 |
| **Modify** | `src/rnd/v0.1.6/2026.03.14-presentation-generator/00-index.md` | +1 row |
| **Modify** | `src/rnd/v0.1.6/2026.03.14-presentation-generator/03-implementation-tracking.md` | Update Phase 6 status |

**Reuse existing**:
- `PresentationModel`, `SlideModel`, `PresenterNotes` from `state.py` — consumed as-is
- `PresentationConfig.get_output_path( ..., file_type="md" )` — already supports `.md`
- `cu.get_project_root()` — for resolving theme file paths
- `_write_yaml()` pattern — duplicated as `_write_marp()` (same 4 lines)
- `voice_io.notify()` — progress breadcrumbs
- Job already reads `state.get( "marp_path" )` and builds clickable links (lines 263-295)

---

## Marp Output Format Reference

Complete example of what the renderer produces for a 3-slide presentation:

```markdown
---
marp: true
theme: default
paginate: true
footer: "Jane Doe | 2026-03-28"
style: |
  section {
    font-family: Inter, sans-serif;
    color: #1F2937;
    background-color: #FFFFFF;
  }
  h1, h2, h3 {
    font-family: Inter, sans-serif;
    color: #2563EB;
  }
  h2 {
    color: #1E40AF;
  }
  code {
    font-family: JetBrains Mono, monospace;
    background-color: #F3F4F6;
  }
  em {
    color: #F59E0B;
  }
---

<!-- _class: lead -->
<!-- _paginate: skip -->

# Three-Layer Caching at Scale
## How We Achieved 3x Latency Improvement

Jane Doe | 2026-03-28

<!--
Talking points:
- Welcome and introduce yourself
- Brief context: this talk covers our caching journey

Timing: 30s
-->

---

# Three-Layer Cache Eliminates Cold Starts

- L1: In-process cache -- handles 80% of requests
- L2: Redis cluster -- shared across instances
- L3: S3 with CloudFront -- cold storage fallback

<!-- VISUAL: diagram | Flowchart showing three cache layers in sequence: L1 (in-process, 80% hit rate) -> L2 (Redis, 15%) -> L3 (S3, 5%). -->

<!--
Transition: So we've seen the problem -- now let's look at what we built.

Talking points:
- Explain the three cache layers left-to-right
- Emphasize L1 handles 80% -- this is the key insight
- Mention the fallback chain is automatic

Timing: 75s
Emphasis: The 80% L1 hit rate -- pause here, let it sink in
-->

---

<!-- _class: lead -->

# Key Takeaways

- Three-layer caching eliminates cold starts completely
- L1 in-process cache is the biggest win (80% hit rate)
- Zero code changes needed for adopters

<!--
Transition: Let me leave you with three things to remember.

Talking points:
- Recap the three main points
- End with the call to action

Timing: 45s
-->
```

---

## Edge Cases & Error Handling

| Edge Case | Handling |
|-----------|---------|
| `presentation is None` | Log warning, return — `marp_path` stays `None` |
| 0 slides in presentation | Render frontmatter only, no slide separators |
| Missing theme file | Fallback to hardcoded default dict, log warning |
| Theme YAML parse error | Fallback to hardcoded default dict, log error |
| `None` subtitle | Omit `## subtitle` line entirely |
| Empty `content_bullets` list | Omit bullet section, slide has title only |
| `None` transition/emphasis in notes | Omit those lines from HTML comment |
| Empty `talking_points` list | Omit "Talking points:" section from comment |
| `visual_type == "text_only"` | No visual placeholder comment |
| `visual_description is None` | Placeholder shows `(no description provided)` |
| Unknown `slide.type` | Fallback to content-style rendering |
| Empty speaker/date on PresentationModel | Title slide omits speaker/date line; footer interpolates to empty |
| Phase 6 exception | Caught, logged, notified as urgent — job continues with YAML only |
| Marp file write fails (permissions) | Exception propagates to try/except in `_render_text_async`, non-fatal |

---

## Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Renderer is stateless (`@staticmethod`) | Yes | Pure function — easier to test, no constructor ceremony |
| CSS generated from theme config | Yes | Keep theme YAML human-readable; CSS is a rendering detail |
| Phase 6 failure is non-fatal | Yes | YAML artifact is the primary deliverable; Marp is enhancement |
| Visual placeholders as HTML comments | `<!-- VISUAL: type \| desc -->` | Machine-parseable for Phase 7 regex replacement |
| Presenter notes as HTML comments | `<!-- ... -->` | Marp standard — visible in presenter view only |
| Slide type dispatch (not if/elif chain) | Dict-based dispatch | Cleaner, extensible, O(1) lookup |
| No INI config changes | Correct | `default_theme` and `templates_path` already exist |
| One CSS style block in frontmatter | Yes | Simpler than external CSS files for MVP |

---

## Verification

### Compilation & Import
1. `python -c "import py_compile; py_compile.compile( 'src/cosa/agents/presentation_generator/renderers/marp_text_renderer.py', doraise=True )"`
2. `PYTHONPATH=src:$PYTHONPATH python -c "from cosa.agents.presentation_generator.renderers import MarpTextRenderer; print( 'OK' )"`

### Unit Tests
3. `pytest src/tests/unit/test_presentation_marp_renderer.py -v` — all new tests pass
4. `pytest src/tests/unit/test_presentation_generator_job.py -v` — integration tests + no regressions
5. `pytest src/tests/unit/ -v` — full suite, no regressions

### Functional Verification
6. Dry-run submission via REST: verify `marp_path` is populated in job artifacts
7. Inspect generated `.md` file: valid Marp frontmatter, correct slide count, presenter notes in comments
8. Open in Marp VS Code extension or `marp --preview`: slides render correctly with theme

### MVP-2 Acceptance Criteria (from `01-strategy-and-design.md` Section 6)
9. Feed MVP-1 YAML through Marp renderer → valid Marp Markdown
10. Theme application: colors, fonts, layout from `default.yaml` visible in rendered output
11. Presenter notes: visible in Marp presenter view (`<!-- ... -->` blocks)
12. Export to PDF: `marp --pdf output.md` produces valid PDF (optional, requires marp-cli)
