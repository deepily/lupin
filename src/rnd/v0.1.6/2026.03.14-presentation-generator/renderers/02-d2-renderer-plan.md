# D2 Renderer — Implementation Plan

**Date**: 2026-03-30
**Phase**: 9B
**Scope**: LLM-generated D2 syntax → d2 CLI → SVG flowcharts and architecture diagrams
**Effort**: 1 session
**Cost**: Free (LLM tokens only)

---

## Context

Mermaid diagrams are functional but visually plain. D2 (Declarative Diagramming) produces significantly prettier output with built-in themes, sketch mode, and modern aesthetics. It fills the gap for architecture diagrams, system overviews, and flowcharts where visual quality matters.

D2 is a modern diagramming language (open source, MIT licensed) that compiles to SVG. The LLM generates D2 syntax the same way it generates Mermaid — from natural-language `visual_description`. The `d2` CLI renders SVG.

**Why D2 over Mermaid for this tier**:
- 8 built-in themes (including sketch/hand-drawn mode)
- Better layout engine (dagre + ELK)
- Native support for containers, connections, icons
- Cleaner SVG output with consistent styling

---

## What We're Building

### Part A: D2Renderer Class
New renderer implementing `VisualRenderer` ABC. Generates D2 syntax via Claude API, renders via `d2` CLI to SVG, returns markdown image reference.

### Part B: D2 Prompt Module
System prompt and builder function for generating valid D2 syntax from natural-language descriptions.

### Part C: API Client Extension
New `call_for_d2()` method on `PresentationAPIClient`.

### Part D: Orchestrator Registration
Register `D2Renderer` for visual types: `flowchart_d2`, `architecture`.

### Part E: Unit Tests
~20 tests covering D2 syntax generation, CLI rendering, SVG output, error handling.

---

## Detailed Implementation

### Part A: `renderers/d2_renderer.py`

```python
class D2Renderer( VisualRenderer ):
    SUPPORTED_TYPES = [ "flowchart_d2", "architecture" ]

    async def render( self, visual_type, visual_description, **kwargs ) -> Optional[ str ]:
        api_client  = kwargs.get( "api_client" )
        slide_title = kwargs.get( "slide_title", "" )
        output_dir  = kwargs.get( "output_dir" )
        slide_index = kwargs.get( "slide_index", 0 )
        theme       = kwargs.get( "d2_theme", 0 )  # 0=default, 1=neutral, 3=terminal, 100=sketch

        # 1. Generate D2 syntax via LLM
        response = await api_client.call_for_d2(
            system_prompt = D2_SYSTEM_PROMPT,
            user_message  = get_d2_prompt( visual_type, visual_description, slide_title )
        )

        # 2. Extract D2 code from response
        d2_code = self._extract_d2_code( response.content )
        if not d2_code: return None

        # 3. Render via d2 CLI → SVG
        output_filename = f"diagram-{slide_index:03d}.svg"
        output_path     = os.path.join( output_dir, output_filename )
        success         = await self._render_d2( d2_code, output_path, theme )
        if not success: return None

        # 4. Return markdown image reference
        rel_path = os.path.join( "visuals", output_filename )
        return f"![{slide_title or visual_description[ :60 ]}]({rel_path})"

    async def _render_d2( self, d2_code, output_path, theme=0 ) -> bool:
        """Execute d2 CLI to render D2 syntax to SVG."""
        result = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: subprocess.run(
                [ "d2", "--theme", str( theme ), "-", output_path ],
                input=d2_code,
                capture_output=True,
                text=True,
                timeout=30
            )
        )
        if result.returncode != 0:
            logger.warning( f"D2 CLI failed: {result.stderr[ :200 ]}" )
            return False
        return os.path.exists( output_path )
```

### Part B: `prompts/d2.py`

**System prompt constraints**:
- Output ONLY valid D2 syntax inside a fenced code block
- Use descriptive node names (not `a`, `b`, `c`)
- Keep diagrams readable: max 12-15 nodes
- Use containers for logical grouping
- Include connection labels where meaningful
- Do NOT include D2 theme directives (applied via CLI flag)

**D2 syntax hints** (keyword → pattern mapping):
- "flow" / "process" → sequential nodes with arrows
- "architecture" / "system" → containers with nested components
- "sequence" → sequence diagram syntax
- "hierarchy" / "tree" → tree layout

### Part C: API Client — `call_for_d2()`

Same pattern as `call_for_mermaid()`:
- `max_tokens = 2048`
- `temperature = 0.3`
- `call_type = "d2"`

### Part D: Orchestrator Registration

```python
if not self.dry_run:
    d2_renderer = D2Renderer( debug=self.debug, verbose=self.verbose )
    registry.register( d2_renderer )
```

---

## New Files

| Action | File | Est. Lines |
|--------|------|-----------|
| **Create** | `src/cosa/agents/presentation_generator/renderers/d2_renderer.py` | ~120 |
| **Create** | `src/cosa/agents/presentation_generator/prompts/d2.py` | ~80 |
| **Modify** | `src/cosa/agents/presentation_generator/api_client.py` | +15 (new method) |
| **Modify** | `src/cosa/agents/presentation_generator/orchestrator.py` | +3 (registry) |
| **Modify** | `src/cosa/agents/presentation_generator/renderers/__init__.py` | +2 (export) |
| **Create** | `src/tests/unit/test_presentation_d2_renderer.py` | ~150 |

## Dependencies

| Dependency | Type | Status |
|-----------|------|--------|
| `d2` | CLI binary | Not installed — `curl -fsSL https://d2lang.com/install.sh \| sh` |
| `subprocess` | stdlib | Available |

## D2 Theme Options

| ID | Name | Best For |
|----|------|----------|
| 0 | Default | Clean, professional |
| 1 | Neutral Grey | Subtle, minimal |
| 3 | Terminal Dark | Dark mode presentations |
| 100 | Sketch (hand-drawn) | Friendly, informal talks |
| 200 | Flagship Terrastruct | Modern, branded |

Theme selection can be driven by the presentation theme config.

## Unit Tests (~20 tests)

| Class | Tests |
|-------|-------|
| `TestD2Renderer` | construction, SUPPORTED_TYPES, render with mock API + CLI |
| `TestD2CodeExtraction` | fenced block, bare code, markdown-wrapped, malformed |
| `TestD2CLIExecution` | success → SVG, d2 not found, syntax error, timeout |
| `TestD2Prompt` | system prompt content, prompt builder, keyword→pattern mapping |
| `TestRegistryIntegration` | D2Renderer registered for flowchart_d2/architecture |

## Verification

1. `py_compile` on all new/modified files
2. `d2 --version` — verify CLI installed
3. Unit tests: `pytest src/tests/unit/test_presentation_d2_renderer.py -v`
4. Manual: `echo "a -> b -> c" | d2 - /tmp/test.svg` — verify SVG output
5. Live test: Submit presentation with architecture slide → verify SVG in `visuals/`

## Open Questions

1. **Theme mapping**: Auto-select D2 theme from presentation theme? Or always use default?
2. **SVG size**: D2 SVGs can be large for complex diagrams. Set max dimensions?
3. **Fallback to Mermaid**: If d2 CLI not installed, fall back to MermaidRenderer for diagram types?
