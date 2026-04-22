# Presentation Generator Phase 7: Visual Rendering — Mermaid + Registry

**Date**: 2026-03-28
**Scope**: Visual renderer protocol, Mermaid LLM generation, placeholder fallback, orchestrator integration, Gate 4
**MVP**: MVP-3 (Visual Rendering)

---

## Context

Phase 6 (Marp Text Rendering) is complete (Session 382). The renderer outputs structured placeholders for visuals in the Marp Markdown:

```html
<!-- VISUAL: diagram | Flowchart showing three cache layers in sequence -->
```

Phase 7 finds these placeholders and replaces them with actual visual content — primarily **Mermaid code blocks** that Marp renders natively. This phase introduces the visual renderer protocol, a registry for type dispatch, an LLM-backed Mermaid generator, and a placeholder fallback for unsupported types.

**Key insight**: Marp renders Mermaid code blocks natively (via the marp-cli Mermaid plugin or VS Code extension). The MermaidRenderer generates Mermaid *syntax* — it does NOT need `mermaid-cli` (`mmdc`) installed on the system. The Marp toolchain handles SVG conversion at presentation export time.

---

## What We're Building

### Part A: Visual Renderer ABC + Registry

Define the abstract renderer protocol and a registry that dispatches visual types to the correct renderer. Fallback to PlaceholderRenderer for any unregistered type.

### Part B: PlaceholderRenderer

Generates visible `[TODO: ...]` markers for visual types that don't have a real renderer yet (screenshot, icon_only, before_after).

### Part C: MermaidRenderer

Calls Claude API to generate Mermaid syntax from natural-language `visual_description`. Extracts and validates the code, wraps it in a fenced code block. Handles both `diagram` and `chart` visual types.

### Part D: Mermaid Generation Prompt

System prompt and prompt builder for Claude to generate valid Mermaid syntax from presentation visual descriptions.

### Part E: API Client Extension

Add `call_for_mermaid()` method to the existing `PresentationAPIClient` — lower temperature (0.3), smaller max_tokens (2048) for code generation.

### Part F: Orchestrator Integration

Replace `_render_visuals_async()` stub: read Marp file → regex-find placeholders → dispatch to registry → replace → rewrite file. Implement Gate 4 with voice I/O summary.

### Part G: Unit Tests

~30 tests covering ABC protocol, placeholder output, registry dispatch, Mermaid extraction, mocked API rendering, prompt structure, and orchestrator integration.

---

## Detailed Implementation

### Part A: Visual Renderer ABC + Registry

**A.1 — Create `renderers/visual_registry.py`**

File: `src/cosa/agents/presentation_generator/renderers/visual_registry.py` (new, ~120 lines)

```python
from abc import ABC, abstractmethod
from typing import ClassVar, List, Optional


class VisualRenderer( ABC ):
    """
    Abstract base class for visual renderers.

    Each renderer handles one or more visual_type values and produces
    inline Marp-compatible markdown content (not file paths).

    Requires:
        - visual_description is a non-empty string

    Ensures:
        - Returns inline markdown content (Mermaid block, table, etc.)
        - Returns None on rendering failure (graceful degradation)
    """
    SUPPORTED_TYPES: ClassVar[ List[ str ] ] = []

    @abstractmethod
    async def render( self, visual_type: str, visual_description: str, **kwargs ) -> Optional[ str ]:
        """
        Generate inline markdown content from a visual description.

        Returns:
            str: Marp-compatible markdown content, or None on failure
        """
        ...


class VisualRendererRegistry:
    """
    Registry mapping visual_type strings to VisualRenderer instances.

    Requires:
        - fallback is a VisualRenderer that handles any type

    Ensures:
        - get() always returns a renderer (never None)
        - Unknown types route to fallback renderer
    """

    def __init__( self, fallback: VisualRenderer, debug: bool = False ):
        self._registry = {}
        self._fallback = fallback
        self.debug     = debug

    def register( self, renderer: VisualRenderer ) -> None:
        """Register a renderer for all its SUPPORTED_TYPES."""
        for visual_type in renderer.SUPPORTED_TYPES:
            self._registry[ visual_type ] = renderer
            if self.debug: print( f"[Registry] Registered: {visual_type} -> {renderer.__class__.__name__}" )

    def get( self, visual_type: str ) -> VisualRenderer:
        """Get renderer for a visual type, falling back to placeholder."""
        renderer = self._registry.get( visual_type, self._fallback )
        if self.debug and visual_type not in self._registry:
            print( f"[Registry] Fallback for: {visual_type}" )
        return renderer

    @property
    def registered_types( self ) -> list:
        """List all registered visual types."""
        return list( self._registry.keys() )
```

**Design note**: The ABC returns **inline markdown content** (e.g., a Mermaid code block string), NOT file paths. This is a deliberate departure from the strategy doc's `Optional[str]` file-path return type — since Marp renders Mermaid inline, we don't need intermediate files.

---

### Part B: PlaceholderRenderer

**B.1 — Create `renderers/placeholder.py`**

File: `src/cosa/agents/presentation_generator/renderers/placeholder.py` (new, ~50 lines)

```python
from typing import Optional
from .visual_registry import VisualRenderer


class PlaceholderRenderer( VisualRenderer ):
    """
    Fallback renderer that emits visible TODO markers.

    Used for visual types without a real renderer (screenshot, icon_only, etc.).
    Always succeeds — never returns None.
    """
    SUPPORTED_TYPES = [ "screenshot", "icon_only", "before_after" ]

    async def render( self, visual_type: str, visual_description: str, **kwargs ) -> Optional[ str ]:
        description = visual_description or "(no description provided)"
        return f"> **[TODO: {visual_type}]** {description}"
```

The output is a Marp blockquote with bold type label — visible in the rendered slides as a clear placeholder.

---

### Part C: MermaidRenderer

**C.1 — Create `renderers/mermaid.py`**

File: `src/cosa/agents/presentation_generator/renderers/mermaid.py` (new, ~130 lines)

```python
import re
import logging
from typing import Optional
from .visual_registry import VisualRenderer

logger = logging.getLogger( __name__ )


class MermaidRenderer( VisualRenderer ):
    """
    LLM-backed renderer that generates Mermaid diagram code.

    Calls Claude API with a visual description, extracts the Mermaid
    syntax from the response, and wraps it in a fenced code block.

    Marp renders Mermaid natively — no mermaid-cli needed.

    Requires:
        - api_client is a PresentationAPIClient instance (passed via kwargs)

    Ensures:
        - Returns a ```mermaid code block on success
        - Returns None on API error (falls back to placeholder)
    """
    SUPPORTED_TYPES = [ "diagram", "chart" ]

    def __init__( self, debug: bool = False, verbose: bool = False ):
        self.debug   = debug
        self.verbose = verbose

    async def render( self, visual_type: str, visual_description: str, **kwargs ) -> Optional[ str ]:
        """
        Generate Mermaid code from natural-language description via Claude API.

        kwargs:
            api_client: PresentationAPIClient (required)
            slide_title: str (optional, for context)

        Returns:
            str: Fenced mermaid code block, or None on failure
        """
        api_client  = kwargs.get( "api_client" )
        slide_title = kwargs.get( "slide_title", "" )

        if api_client is None:
            logger.warning( "MermaidRenderer: No api_client provided" )
            return None

        try:
            from ..prompts.visual import MERMAID_SYSTEM_PROMPT, get_mermaid_prompt

            prompt = get_mermaid_prompt(
                visual_type        = visual_type,
                visual_description = visual_description,
                slide_title        = slide_title,
            )

            response = await api_client.call_for_mermaid(
                system_prompt = MERMAID_SYSTEM_PROMPT,
                user_message  = prompt,
            )

            mermaid_code = self._extract_mermaid( response.content )
            if mermaid_code:
                if self.debug: print( f"[MermaidRenderer] Generated {len( mermaid_code )} chars for: {slide_title[ :40 ]}" )
                return f"```mermaid\n{mermaid_code}\n```"
            else:
                logger.warning( f"MermaidRenderer: Could not extract Mermaid from response for: {slide_title[ :40 ]}" )
                return None

        except Exception as e:
            logger.error( f"MermaidRenderer failed: {e}" )
            return None

    @staticmethod
    def _extract_mermaid( response_content: str ) -> Optional[ str ]:
        """
        Extract Mermaid code from Claude's response.

        Handles:
            - Fenced ```mermaid ... ``` blocks
            - Bare code starting with graph/flowchart/sequenceDiagram/etc.

        Returns:
            str: Raw Mermaid code (no fences), or None if not found
        """
        # Try fenced block first
        match = re.search( r"```(?:mermaid)?\s*\n(.*?)```", response_content, re.DOTALL )
        if match:
            return match.group( 1 ).strip()

        # Try bare Mermaid (starts with known directive)
        mermaid_starts = [
            "graph ", "flowchart ", "sequenceDiagram", "classDiagram",
            "stateDiagram", "erDiagram", "gantt", "pie ", "gitgraph",
            "mindmap", "timeline", "quadrantChart", "xychart",
        ]
        for start in mermaid_starts:
            if start in response_content:
                # Extract from directive to end
                idx = response_content.index( start )
                return response_content[ idx: ].strip()

        return None
```

---

### Part D: Mermaid Generation Prompt

**D.1 — Create `prompts/visual.py`**

File: `src/cosa/agents/presentation_generator/prompts/visual.py` (new, ~150 lines)

System prompt and prompt builder for Mermaid code generation.

**`MERMAID_SYSTEM_PROMPT`**: Instructs Claude to:
- Generate valid Mermaid syntax (NOT SVG, NOT ASCII art)
- Use appropriate diagram types based on the description (flowchart, sequence, class, state, ER, pie, gantt, mindmap, timeline)
- Keep diagrams simple and readable (max ~15 nodes for presentation slides)
- Use descriptive node labels (not single letters)
- Output ONLY the Mermaid code in a fenced block — no explanation before or after
- Include style directives for visual clarity when appropriate

**`get_mermaid_prompt()`**: Builds user message with:
- `visual_type`: "diagram" or "chart"
- `visual_description`: Natural-language spec from elaboration phase
- `slide_title`: Context for what the diagram should convey

**`MERMAID_DIAGRAM_TYPE_HINTS`**: Dict mapping description keywords to Mermaid diagram types:
- "flow", "process", "pipeline" → `flowchart TD`
- "sequence", "interaction", "request" → `sequenceDiagram`
- "class", "inheritance", "hierarchy" → `classDiagram`
- "state", "lifecycle" → `stateDiagram-v2`
- "relationship", "entity" → `erDiagram`
- "pie", "distribution", "breakdown" → `pie`
- "timeline", "schedule", "gantt" → `gantt`
- Default → `flowchart TD`

---

### Part E: API Client Extension

**E.1 — Add `call_for_mermaid()` to `api_client.py`**

File: `src/cosa/agents/presentation_generator/api_client.py` (modify)

Add new method after the existing `call_for_elaboration()`:

```python
async def call_for_mermaid(
    self,
    system_prompt: str,
    user_message: str,
    max_tokens: int = 2048,
    temperature: float = 0.3
) -> "APIResponse":
    """
    Generate Mermaid diagram code via Claude API.

    Lower temperature and smaller max_tokens than content generation
    for more deterministic, concise code output.

    Requires:
        - system_prompt is a non-empty string
        - user_message is a non-empty string

    Ensures:
        - Returns APIResponse with Mermaid code in content
        - Cost tracked in cost_estimate

    Returns:
        APIResponse with generated Mermaid content
    """
    return await self._call_api(
        model         = self.config.content_model,
        system_prompt = system_prompt,
        user_message  = user_message,
        call_type     = "mermaid",
        max_tokens    = max_tokens,
        temperature   = temperature,
    )
```

---

### Part F: Orchestrator Integration

**F.1 — Replace `_render_visuals_async()` stub**

File: `src/cosa/agents/presentation_generator/orchestrator.py` (replace lines 1119-1126)

Implementation:

1. Guard: if `presentation is None` or `marp_path` is None, skip
2. Read the Marp file content from `self._presentation_state[ "marp_path" ]`
3. Find all `<!-- VISUAL: type | description -->` placeholders via regex
4. Build the visual renderer registry:
   - `PlaceholderRenderer` as fallback
   - `MermaidRenderer` registered for `diagram`, `chart`
   - In `dry_run` mode: use PlaceholderRenderer for ALL types (no API calls)
5. For each placeholder:
   - Extract `visual_type` and `visual_description`
   - Get renderer from registry
   - Call `await renderer.render( visual_type, visual_description, api_client=self.api_client, slide_title=slide_title )`
   - If result is not None: replace placeholder with rendered content
   - If result is None: replace with PlaceholderRenderer output (fallback)
   - Notify progress per visual: `await voice_io.notify( "Rendered: {slide_title[:40]}...", priority="low" )`
6. Rewrite the Marp file with replaced content
7. Store visual count in `self._presentation_state[ "visuals_rendered" ]`

**Regex pattern**: `r"<!-- VISUAL: (\S+) \| (.+?) -->"`

**Helper methods**:
- `_build_visual_registry( dry_run: bool ) -> VisualRendererRegistry` — factory for building the registry
- Use existing `_read_file()` pattern or `asyncio.to_thread( open(...).read )` for file reading

**F.2 — Implement Gate 4**

File: `src/cosa/agents/presentation_generator/orchestrator.py` (replace lines 1489-1492)

Replace auto-approve stub with voice I/O summary:

1. If `dry_run`: auto-approve (no voice interaction)
2. Build summary: count of visuals by type (e.g., "3 diagrams rendered, 1 placeholder")
3. Present via `ask_yes_no()` or `present_choices()`:
   - **Approve** — proceed to delivery
   - **Revise** — user provides feedback, re-run visual rendering (not re-run content phases)
   - **Cancel** — abort
4. Voice I/O failure → auto-approve

**Design note**: Gate 4 revision loops only re-run Phase 7 (visual rendering), not Phases 1-5 (content generation). The user might say "make the flowchart horizontal instead of vertical" — this re-renders only the affected Mermaid diagram.

**F.3 — Update `renderers/__init__.py`**

File: `src/cosa/agents/presentation_generator/renderers/__init__.py`

Add exports:

```python
from .visual_registry import VisualRenderer, VisualRendererRegistry
from .mermaid import MermaidRenderer
from .placeholder import PlaceholderRenderer
```

**F.4 — Update `prompts/__init__.py`**

File: `src/cosa/agents/presentation_generator/prompts/__init__.py`

Add import for `visual` module.

---

### Part G: Unit Tests

**G.1 — Create test file**

File: `src/tests/unit/test_presentation_visual_renderer.py` (new, ~350 lines)

**Test classes** (~30 tests):

```
class TestVisualRendererABC:
    test_abc_cannot_instantiate                # Cannot create VisualRenderer directly
    test_abc_subclass_must_implement_render     # Subclass without render() raises TypeError

class TestPlaceholderRenderer:
    test_placeholder_output_format             # Returns "> **[TODO: ...]** description"
    test_placeholder_supported_types           # SUPPORTED_TYPES contains expected values
    test_placeholder_none_description          # Handles None description gracefully
    test_placeholder_never_returns_none        # Always returns a string

class TestVisualRendererRegistry:
    test_registry_get_registered_type          # Returns correct renderer for registered type
    test_registry_get_unregistered_type        # Returns fallback for unknown type
    test_registry_register_multiple            # Multiple types from one renderer
    test_registry_registered_types_list        # registered_types returns correct list
    test_registry_fallback_is_never_none       # get() never returns None

class TestMermaidExtraction:
    test_extract_fenced_mermaid                # ```mermaid ... ``` extracted correctly
    test_extract_bare_fenced                   # ``` ... ``` (no mermaid label)
    test_extract_bare_flowchart                # Bare "flowchart TD" detected
    test_extract_bare_sequence                 # Bare "sequenceDiagram" detected
    test_extract_no_mermaid                    # Returns None when no Mermaid found
    test_extract_strips_whitespace             # Extracted code is trimmed

class TestMermaidRendererMocked:
    test_render_returns_fenced_block           # Output wrapped in ```mermaid ... ```
    test_render_no_api_client_returns_none     # Missing api_client → None
    test_render_api_error_returns_none         # API exception → None (non-fatal)
    test_render_passes_slide_title             # slide_title forwarded to prompt

class TestMermaidPrompt:
    test_system_prompt_mentions_mermaid        # System prompt contains "Mermaid"
    test_prompt_includes_description           # Visual description in user message
    test_prompt_includes_slide_title           # Slide title for context
    test_diagram_type_hints                    # Keyword → diagram type mapping

class TestOrchestratorVisualIntegration:
    test_placeholder_regex_finds_visuals       # Regex matches <!-- VISUAL: ... --> comments
    test_placeholder_regex_skips_text_only     # No match on slides without visuals
    test_dry_run_uses_placeholders_only        # Dry run never calls API
```

---

## Implementation Order

| Step | Part | What | Dependencies |
|------|------|------|-------------|
| 0 | — | Serialize plan + update `00-index.md` | None |
| 1 | A | `visual_registry.py` (ABC + Registry) | None |
| 2 | B | `placeholder.py` (PlaceholderRenderer) | A |
| 3 | D | `prompts/visual.py` (Mermaid prompt) | None |
| 4 | E | `api_client.py` — add `call_for_mermaid()` | None |
| 5 | C | `mermaid.py` (MermaidRenderer) | A, D, E |
| 6 | F.3-F.4 | Update `__init__.py` files | A, B, C |
| 7 | G | Unit tests (write alongside) | A, B, C, D |
| 8 | F.1 | `_render_visuals_async()` in orchestrator | All renderers |
| 9 | F.2 | Gate 4 implementation | F.1 |
| 10 | — | Full unit suite — verify no regressions | All |

---

## Files Summary

| Action | File | Est. Lines |
|--------|------|-----------|
| **Create** | `renderers/visual_registry.py` | ~120 |
| **Create** | `renderers/placeholder.py` | ~50 |
| **Create** | `renderers/mermaid.py` | ~130 |
| **Create** | `prompts/visual.py` | ~150 |
| **Create** | `src/tests/unit/test_presentation_visual_renderer.py` | ~350 |
| **Modify** | `api_client.py` — add `call_for_mermaid()` | +30 |
| **Modify** | `orchestrator.py` — Phase 7 + Gate 4 | +100 |
| **Modify** | `renderers/__init__.py` — add exports | +5 |
| **Modify** | `prompts/__init__.py` — add visual import | +1 |

**Reuse existing**:
- `PresentationAPIClient._call_api()` — shared API call mechanism
- `CostEstimate.add_usage()` — Mermaid calls tracked automatically
- `voice_io.notify()` / `voice_io.present_choices()` — Gate 4 interaction
- `MarpTextRenderer._render_visual_placeholder()` format — regex target

---

## Edge Cases & Error Handling

| Edge Case | Handling |
|-----------|---------|
| `presentation is None` | Skip Phase 7, log warning |
| `marp_path is None` (Phase 6 failed) | Skip Phase 7, log warning |
| No visual placeholders in Marp file | Phase 7 completes instantly (no-op) |
| API call fails for one Mermaid diagram | Fall back to PlaceholderRenderer for that slide |
| Claude returns invalid Mermaid syntax | Marp will show render error — acceptable for MVP |
| All visuals are `text_only` | No placeholders to find, Phase 7 is no-op |
| `dry_run` mode | ALL types use PlaceholderRenderer (no API calls) |
| Registry has no renderer for type | Fallback to PlaceholderRenderer |
| `visual_description is None` | PlaceholderRenderer shows "(no description provided)" |
| Gate 4 voice I/O failure | Auto-approve |
| Marp file read/write error | Exception caught, logged — non-fatal |

---

## Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Renderers return inline content, not file paths | Yes | Marp renders Mermaid inline — no intermediate files needed |
| No mermaid-cli dependency | Correct | Marp toolchain handles SVG rendering at export time |
| Lower temperature for Mermaid (0.3 vs 0.7) | Yes | Code generation benefits from determinism |
| Dry run uses PlaceholderRenderer for all types | Yes | No API costs during testing |
| Gate 4 revision re-runs Phase 7 only | Yes | Content (Phases 1-5) is already approved at Gates 1-3 |
| `code_block` and `table` types NOT registered in MVP | Correct | Both render natively in Marp Markdown — the elaboration phase already formats them correctly in `visual_description`. Phase 7 just needs PlaceholderRenderer with a note to verify formatting. |
| MermaidRenderer handles both `diagram` and `chart` | Yes | Mermaid supports pie/xychart/gantt for charts |

---

## Verification

1. `py_compile` on all new Python files
2. Import chain: `from cosa.agents.presentation_generator.renderers import MermaidRenderer, PlaceholderRenderer, VisualRendererRegistry`
3. `pytest src/tests/unit/test_presentation_visual_renderer.py -v` — all pass
4. `pytest src/tests/unit/ -v` — no regressions
5. Dry-run submission: all visuals replaced with placeholder markers
6. Live run with real API: Mermaid code blocks in Marp file, renderable by Marp
7. Gate 4: visual summary presented via voice I/O
