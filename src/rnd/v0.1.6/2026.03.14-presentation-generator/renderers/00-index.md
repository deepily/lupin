# Visual Renderer Expansion — Implementation Plans

**Created**: 2026-03-30 (Session 383)
**Parent**: [Visual Rendering Expansion Plan](../11-visual-rendering-expansion-plan.md)
**Status**: Planning

---

## Document Index

| # | Document | Renderer | Visual Types | Status |
|---|----------|----------|-------------|--------|
| 01 | [Matplotlib Renderer](01-matplotlib-renderer-plan.md) | `MatplotlibRenderer` | chart, plot, graph, data_viz | Planning |
| 02 | [D2 Renderer](02-d2-renderer-plan.md) | `D2Renderer` | flowchart_d2, architecture | Planning |
| 03 | [Nano Banana Renderer](03-nano-banana-renderer-plan.md) | `NanoBananaRenderer` | hero_image, infographic, title_background, icon | Planning |
| 04 | [Veo Renderer](04-veo-renderer-plan.md) | `VeoRenderer` | flow_animation, title_video, process_explanation | Planning |
| 05 | [Theme Integration](05-theme-integration-plan.md) | N/A (cross-cutting) | All | Planning |

## Implementation Priority

| Phase | Renderer | Effort | External Deps | Cost Model |
|-------|----------|--------|--------------|------------|
| 9A | MatplotlibRenderer | 1-2 sessions | matplotlib, seaborn (pip) | Free |
| 9B | D2Renderer | 1 session | d2 CLI binary | Free |
| 10A | NanoBananaRenderer | 1-2 sessions | google-genai SDK (installed) | $0.045-$0.151/image |
| 10B | VeoRenderer | 1-2 sessions | google-genai SDK (installed) | $0.20/sec (1080p) |
| 11 | Theme Integration | 1 session | Phases 9-10 complete | N/A |

## Architecture Summary

All renderers implement the same ABC:

```python
class VisualRenderer( ABC ):
    SUPPORTED_TYPES: ClassVar[ List[ str ] ] = []

    @abstractmethod
    async def render( self, visual_type: str, visual_description: str, **kwargs ) -> Optional[ str ]:
        ...
```

```mermaid
graph LR
    subgraph Existing["EXISTING (Built)"]
        D["diagram, chart"] --> MR[MermaidRenderer]
        FB["fallback"] --> PH[PlaceholderRenderer]
    end

    subgraph Tier1["TIER 1: Free Renderers"]
        CH["chart, plot, graph, data_viz"] --> MPL[MatplotlibRenderer]
        FD["flowchart_d2, architecture"] --> D2R[D2Renderer]
    end

    subgraph Tier2["TIER 2: Paid Image Gen"]
        HI["hero_image, infographic, title_background, icon"] --> NBR[NanoBananaRenderer]
    end

    subgraph Tier3["TIER 3: Paid Video Gen"]
        FA["flow_animation, title_video, process_explanation"] --> VR[VeoRenderer]
    end
```

## Key Pattern: File-Producing Renderers

Current renderers return inline markdown. New renderers produce files:

| Renderer | Output File | Marp Embedding |
|----------|------------|---------------|
| Matplotlib | PNG/SVG | `![description](./visuals/chart-001.png)` |
| D2 | SVG | `![description](./visuals/diagram-001.svg)` |
| Nano Banana | PNG | `![description](./visuals/hero-001.png)` |
| Veo | MP4 + PNG frame | `<video>` for HTML, `![still](frame.png)` for PDF |

All file-producing renderers receive `output_dir` via kwargs. The orchestrator creates a `visuals/` subdirectory next to the Marp file.
