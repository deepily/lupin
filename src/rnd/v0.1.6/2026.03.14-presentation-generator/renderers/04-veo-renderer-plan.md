# Veo Renderer — Implementation Plan

**Date**: 2026-03-30
**Phase**: 10B
**Scope**: Gemini API (Veo 2) → MP4 for flow animations, title videos, process explanations
**Effort**: 1-2 sessions
**Cost**: $0.20/sec at 1080p

---

## Context

Video is the highest-impact visual upgrade for presentations. A 6-8 second ambient title video transforms a static title slide into something cinematic. A process explanation animation replaces a wall-of-text diagram with a watchable walkthrough.

Google Veo 2 generates 1080p video from text prompts via the Gemini API. Up to 8 seconds per generation. The same API credential and SDK (`google-genai`) used for Nano Banana image generation.

**Use cases in presentations**:
- **Title videos**: Abstract ambient backgrounds (tech-themed, industry-specific)
- **Flow animations**: Step-by-step process walkthroughs
- **Process explanations**: System behavior visualization, data pipelines, algorithm steps

**Key constraint**: Video works in HTML exports (Marp supports `<video>` tags) but NOT in PDF/PPTX. Strategy: generate video + static frame. HTML gets video, PDF/PPTX gets the frame image with a note.

---

## What We're Building

### Part A: VeoRenderer Class
New renderer implementing `VisualRenderer` ABC. Generates video via Veo 2, extracts a static frame, returns appropriate markdown for the export format.

### Part B: Video Generation Prompt Module
System prompt and builder function optimized for short-form video generation from slide descriptions.

### Part C: GeminiImageClient Extension
Add `generate_video()` method to the shared `GeminiImageClient` (created in Phase 10A).

### Part D: Frame Extraction
Extract a representative still frame from generated MP4 for PDF/PPTX fallback.

### Part E: Orchestrator Registration
Register `VeoRenderer` for visual types: `flow_animation`, `title_video`, `process_explanation`.

### Part F: Unit Tests
~20 tests covering video generation, frame extraction, dual output, error handling.

---

## Detailed Implementation

### Part A: `renderers/veo_renderer.py`

```python
class VeoRenderer( VisualRenderer ):
    SUPPORTED_TYPES = [ "flow_animation", "title_video", "process_explanation" ]

    def __init__( self, gemini_client=None, debug=False, verbose=False ):
        self.gemini_client = gemini_client
        self.debug         = debug
        self.verbose       = verbose

    async def render( self, visual_type, visual_description, **kwargs ) -> Optional[ str ]:
        slide_title = kwargs.get( "slide_title", "" )
        output_dir  = kwargs.get( "output_dir" )
        slide_index = kwargs.get( "slide_index", 0 )

        if self.gemini_client is None: return None

        # 1. Build video generation prompt
        prompt = get_video_prompt( visual_type, visual_description, slide_title )

        # 2. Generate video
        video_filename = f"video-{slide_index:03d}.mp4"
        video_path     = os.path.join( output_dir, video_filename )
        success        = await self.gemini_client.generate_video( prompt, video_path )
        if not success: return None

        # 3. Extract static frame for PDF/PPTX fallback
        frame_filename = f"video-{slide_index:03d}-frame.png"
        frame_path     = os.path.join( output_dir, frame_filename )
        self._extract_frame( video_path, frame_path )

        # 4. Return dual-format markdown
        video_rel  = os.path.join( "visuals", video_filename )
        frame_rel  = os.path.join( "visuals", frame_filename )
        alt_text   = slide_title or visual_description[ :60 ]

        # HTML: video tag. PDF/PPTX: static image + note.
        return (
            f'<video src="{video_rel}" autoplay muted loop '
            f'style="width:100%;max-height:500px;object-fit:cover;">'
            f'</video>\n\n'
            f'<!-- PDF/PPTX fallback: ![{alt_text}]({frame_rel}) -->'
        )

    def _extract_frame( self, video_path, frame_path ):
        """Extract frame at 1-second mark from MP4 using ffmpeg."""
        try:
            subprocess.run(
                [ "ffmpeg", "-i", video_path, "-ss", "1", "-frames:v", "1",
                  "-q:v", "2", frame_path, "-y" ],
                capture_output=True,
                timeout=15
            )
        except Exception as e:
            logger.warning( f"Frame extraction failed: {e}" )
```

### Part B: `prompts/video_gen.py`

**Prompt engineering by visual type**:

- **title_video**: "Slow cinematic pan over abstract {theme} environment, soft lighting, professional atmosphere, no text, no people, 8 seconds, smooth motion"
- **flow_animation**: "Step-by-step animation showing {description}, each step appearing sequentially, clean white background, professional diagram style, 6 seconds"
- **process_explanation**: "Visual explanation of {description}, data flowing through stages, smooth transitions between phases, technical visualization style, 8 seconds"

**Style modifiers**:
- Always include: "1080p, high quality, smooth motion"
- Never include: "text overlays" (Marp handles text)
- For title_video: "no people, abstract, ambient"
- For process: "diagram style, clean, labeled stages"

### Part C: GeminiImageClient — `generate_video()`

```python
async def generate_video( self, prompt, output_path, duration_seconds=8 ) -> bool:
    """Generate video via Veo 2 model."""
    client = self._get_client()
    response = await asyncio.get_event_loop().run_in_executor(
        None,
        lambda: client.models.generate_videos(
            model  = "veo-2.0-generate-001",  # Verify model ID at implementation
            prompt = prompt,
            config = {
                "duration_seconds" : duration_seconds,
                "resolution"       : "1080p",
            }
        )
    )
    # Veo returns video bytes — save to file
    if response.generated_videos:
        video = response.generated_videos[ 0 ]
        with open( output_path, "wb" ) as f:
            f.write( video.video_bytes )
        self._track_video_cost( duration_seconds )
        return True
    return False
```

**Note**: Exact Veo 2 API method signature needs verification at implementation time. The `google-genai` SDK's video generation interface may differ.

### Part D: Orchestrator Registration

```python
if not self.dry_run:
    # gemini_client already created for NanoBananaRenderer
    veo = VeoRenderer( gemini_client=gemini_client, debug=self.debug )
    registry.register( veo )
```

---

## Veo 2 API Pricing (March 2026)

| Tier | Price | Resolution | Max Duration |
|------|-------|-----------|-------------|
| Veo 2 (Gemini API) | $0.20/sec | 1080p | 8 sec |
| Veo 2 (Vertex AI) | $0.50/sec | 1080p | 8 sec |

**Cost per presentation** (typical: 1 title + 1 process = 14 sec): **$2.80**

## New Files

| Action | File | Est. Lines |
|--------|------|-----------|
| **Create** | `src/cosa/agents/presentation_generator/renderers/veo_renderer.py` | ~120 |
| **Create** | `src/cosa/agents/presentation_generator/prompts/video_gen.py` | ~100 |
| **Modify** | `src/cosa/agents/presentation_generator/gemini_client.py` | +30 (generate_video method) |
| **Modify** | `src/cosa/agents/presentation_generator/orchestrator.py` | +3 (registry) |
| **Modify** | `src/cosa/agents/presentation_generator/renderers/__init__.py` | +2 (export) |
| **Modify** | `src/conf/lupin-app.ini` | +2 (video config keys) |
| **Modify** | `src/conf/lupin-app-splainer.ini` | +2 (explanations) |
| **Create** | `src/tests/unit/test_presentation_veo_renderer.py` | ~150 |

## Dependencies

| Dependency | Type | Status |
|-----------|------|--------|
| `google-genai` | pip | Already installed (v1.29.0) |
| `ffmpeg` | CLI binary | Likely installed (used by podcast TTS pipeline) |
| Gemini API key | Credential | Same as NanoBananaRenderer (Phase 10A) |
| `GeminiImageClient` | Internal | Created in Phase 10A |

## Unit Tests (~20 tests)

| Class | Tests |
|-------|-------|
| `TestVeoRenderer` | construction, SUPPORTED_TYPES, render with mock client |
| `TestVideoGeneration` | mock API success, API failure, timeout |
| `TestFrameExtraction` | ffmpeg success, ffmpeg not found, corrupt video |
| `TestDualOutput` | HTML video tag format, PDF fallback comment, alt text |
| `TestVideoPrompt` | prompt builder for each visual_type, style modifiers, duration control |
| `TestRegistryIntegration` | VeoRenderer registered for flow_animation/title_video/process_explanation |
| `TestCostTracking` | per-second cost calculation, budget enforcement |

## Verification

1. `py_compile` on all new/modified files
2. `ffmpeg -version` — verify CLI available
3. Unit tests: `pytest src/tests/unit/test_presentation_veo_renderer.py -v`
4. Dry-run: PlaceholderRenderer used (VeoRenderer disabled)
5. Live test: Submit presentation with title_video type → verify MP4 + frame PNG in `visuals/`
6. HTML export: Open in browser, verify video autoplays
7. Cost check: Verify cost tracking ($0.20/sec × duration)

## Open Questions

1. **Video duration**: Fixed 8 sec for all types, or vary? Title: 8 sec (loop), process: 6 sec?
2. **Veo 2 vs Veo 3.1**: Veo 3.1 has audio generation ($0.40/sec). Worth the 2x cost for narrated explanations?
3. **ffmpeg dependency**: If ffmpeg not installed, skip frame extraction? Or fail gracefully?
4. **Budget control**: Should the orchestrator enforce a video budget cap (e.g., max 2 videos per deck)?
5. **Caching**: Title video prompts may be similar across presentations. Cache by prompt hash?
6. **Marp compatibility**: Verify `<video>` tag renders correctly in marp-cli HTML export
