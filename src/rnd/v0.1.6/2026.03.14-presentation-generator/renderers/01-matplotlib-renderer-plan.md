# Matplotlib Renderer — Implementation Plan

**Date**: 2026-03-30
**Phase**: 9A
**Scope**: LLM-generated Python code → sandboxed execution → PNG/SVG charts
**Effort**: 1-2 sessions
**Cost**: Free (LLM tokens only)

---

## Context

The Presentation Generator's visual pipeline currently handles structural diagrams (Mermaid) but has no data visualization capability. Slides with `visual_type: chart` fall through to PlaceholderRenderer, producing `[TODO: chart]` markers.

Matplotlib is the standard Python data visualization library. The approach: LLM generates Python plotting code from the `visual_description`, we execute it in CoSA's existing sandboxed runner (`util_code_runner.py`), and capture the output PNG/SVG.

This is the highest-impact renderer because data-driven slides (comparisons, trends, metrics) are extremely common in technical presentations.

---

## What We're Building

### Part A: MatplotlibRenderer Class
New renderer implementing `VisualRenderer` ABC. Generates Python plotting code via Claude API, executes in sandbox, returns markdown image reference.

### Part B: Matplotlib Prompt Module
System prompt and builder function for generating valid, self-contained Matplotlib code from natural-language chart descriptions.

### Part C: API Client Extension
New `call_for_matplotlib()` method on `PresentationAPIClient` — lower temperature (0.2), code-generation-optimized parameters.

### Part D: Orchestrator Registration
Register `MatplotlibRenderer` in `_build_visual_registry()` for visual types: `chart`, `plot`, `graph`, `data_viz`.

### Part E: Unit Tests
~25 tests covering code generation, sandbox execution, image output, error handling.

---

## Detailed Implementation

### Part A: `renderers/matplotlib_renderer.py`

```python
class MatplotlibRenderer( VisualRenderer ):
    SUPPORTED_TYPES = [ "chart", "plot", "graph", "data_viz" ]

    async def render( self, visual_type, visual_description, **kwargs ) -> Optional[ str ]:
        api_client  = kwargs.get( "api_client" )
        slide_title = kwargs.get( "slide_title", "" )
        output_dir  = kwargs.get( "output_dir" )
        slide_index = kwargs.get( "slide_index", 0 )

        # 1. Generate Python code via LLM
        response = await api_client.call_for_matplotlib(
            system_prompt = MATPLOTLIB_SYSTEM_PROMPT,
            user_message  = get_matplotlib_prompt( visual_type, visual_description, slide_title )
        )

        # 2. Extract Python code from response
        python_code = self._extract_python_code( response.content )
        if not python_code: return None

        # 3. Inject output path + savefig() call
        output_filename = f"chart-{slide_index:03d}.png"
        output_path     = os.path.join( output_dir, output_filename )
        python_code     = self._inject_savefig( python_code, output_path )

        # 4. Execute in sandbox
        result = self._execute_code( python_code )
        if result[ "return_code" ] != 0: return None

        # 5. Verify file exists
        if not os.path.exists( output_path ): return None

        # 6. Return markdown image reference (relative path)
        rel_path = os.path.join( "visuals", output_filename )
        return f"![{slide_title or visual_description[ :60 ]}]({rel_path})"
```

**Key design decisions**:
- `_inject_savefig()` appends `plt.savefig(path, dpi=150, bbox_inches='tight')` + `plt.close()` to ensure clean output
- Uses `util_code_runner.assemble_and_run_solution()` for sandboxed execution with timeout
- PNG at 150 DPI (good balance for slides — 1920x1080 equivalent)
- Returns relative path so Marp can resolve it at export time

### Part B: `prompts/matplotlib.py`

**System prompt constraints**:
- Output ONLY valid Python code inside a fenced code block
- Must import matplotlib.pyplot and any needed libraries
- Must NOT call `plt.show()` (headless execution)
- Must generate sample/representative data if real data unavailable
- Keep charts simple: max 6 data series, clear labels, readable fonts
- Use a clean style (seaborn whitegrid or default)

**Prompt builder** receives: `visual_type`, `visual_description`, `slide_title`
- Suggests chart type based on keywords (bar, line, scatter, pie, heatmap)
- Includes style constraints from presentation theme (colors, fonts)

### Part C: API Client — `call_for_matplotlib()`

Same pattern as `call_for_mermaid()`:
- `max_tokens = 4096` (code can be longer than Mermaid)
- `temperature = 0.2` (even more deterministic for code)
- `call_type = "matplotlib"` (for cost tracking)

### Part D: Orchestrator Registration

In `_build_visual_registry()`:
```python
if not self.dry_run:
    matplotlib_renderer = MatplotlibRenderer( debug=self.debug, verbose=self.verbose )
    registry.register( matplotlib_renderer )
```

### Part E: Orchestrator — output_dir Setup

Before rendering loop, create visuals directory:
```python
marp_dir   = os.path.dirname( marp_path )
visuals_dir = os.path.join( marp_dir, "visuals" )
os.makedirs( visuals_dir, exist_ok=True )
```

Pass `output_dir=visuals_dir` and `slide_index=i` in kwargs to all renderers.

---

## New Files

| Action | File | Est. Lines |
|--------|------|-----------|
| **Create** | `src/cosa/agents/presentation_generator/renderers/matplotlib_renderer.py` | ~150 |
| **Create** | `src/cosa/agents/presentation_generator/prompts/matplotlib.py` | ~100 |
| **Modify** | `src/cosa/agents/presentation_generator/api_client.py` | +20 (new method) |
| **Modify** | `src/cosa/agents/presentation_generator/orchestrator.py` | +15 (registry + output_dir) |
| **Modify** | `src/cosa/agents/presentation_generator/renderers/__init__.py` | +2 (export) |
| **Create** | `src/tests/unit/test_presentation_matplotlib_renderer.py` | ~200 |

## Dependencies

| Dependency | Type | Status |
|-----------|------|--------|
| `matplotlib` | pip | Likely already installed (used by other CoSA modules) |
| `seaborn` | pip | Check — may need `pip install seaborn` |
| `util_code_runner.py` | CoSA module | Exists at `src/cosa/utils/util_code_runner.py` |

## Unit Tests (~25 tests)

| Class | Tests |
|-------|-------|
| `TestMatplotlibRenderer` | construction, SUPPORTED_TYPES, render with mock API |
| `TestPythonCodeExtraction` | fenced block, bare code, markdown-wrapped, malformed |
| `TestSavefigInjection` | inject into clean code, code with existing plt.show(), code with existing savefig() |
| `TestSandboxExecution` | success with output file, timeout, syntax error, import error |
| `TestMatplotlibPrompt` | system prompt content, prompt builder with all chart types, keyword→type mapping |
| `TestRegistryIntegration` | MatplotlibRenderer registered for chart/plot/graph/data_viz |

## Verification

1. `py_compile` on all new/modified files
2. Import chain: `from cosa.agents.presentation_generator.renderers.matplotlib_renderer import MatplotlibRenderer`
3. Unit tests: `pytest src/tests/unit/test_presentation_matplotlib_renderer.py -v`
4. Dry-run: PlaceholderRenderer still used for chart types (MatplotlibRenderer disabled)
5. Live test: Submit presentation with data-heavy source → verify PNG generated in `visuals/` dir

## Open Questions

1. **Chart type dispatch**: Should the LLM choose chart type, or should we map keywords → chart type before prompting?
2. **Data generation**: When `visual_description` says "bar chart comparing X, Y, Z" but no numbers are given, should the LLM invent representative data?
3. **Style injection**: How much theme info to pass? Just colors, or full Matplotlib rcParams?
4. **SVG vs PNG**: SVG scales better in Marp, but Matplotlib SVG output can be large. Default to PNG?
