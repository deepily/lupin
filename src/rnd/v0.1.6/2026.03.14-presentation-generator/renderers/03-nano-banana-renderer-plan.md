# Nano Banana Renderer — Implementation Plan

**Date**: 2026-03-30
**Phase**: 10A
**Scope**: Gemini API (Nano Banana 2) → PNG for hero images, infographics, title backgrounds
**Effort**: 1-2 sessions
**Cost**: $0.045-$0.151/image (resolution-dependent)

---

## Context

Slides with visual types like `hero_image`, `infographic`, and `title_background` currently produce placeholder markers. These are the "polish" visuals that transform a functional deck into a professional one — background imagery for title slides, conceptual infographics for key points, and brand-aligned icons.

Nano Banana 2 is Google's Gemini-based image generation model (launched Feb 2026). It's available via the same Gemini API we already use, has a free tier for development, and produces high-quality images with SynthID watermarking.

**Why Nano Banana 2**:
- Same Gemini API credential we already have configured
- Free tier via AI Studio for dev/testing
- Batch API at 50% discount for production
- Sharp text rendering (important for infographics)
- Nano Banana Pro upgrade path for 4K output

---

## What We're Building

### Part A: GeminiImageClient
Shared Gemini API client for image generation. Used by both NanoBananaRenderer and VeoRenderer (Phase 10B). Handles auth, API calls, cost tracking.

### Part B: NanoBananaRenderer Class
New renderer implementing `VisualRenderer` ABC. Builds image generation prompt from `visual_description` + slide context, calls Gemini API, saves PNG, returns markdown image reference.

### Part C: Image Generation Prompt Module
System prompt and builder function for generating effective image prompts from slide descriptions.

### Part D: INI Configuration
Config keys for resolution, style preferences, budget limits.

### Part E: Orchestrator Registration
Register `NanoBananaRenderer` for visual types: `hero_image`, `infographic`, `title_background`, `icon`.

### Part F: Unit Tests
~20 tests covering prompt construction, API mocking, image saving, error handling.

---

## Detailed Implementation

### Part A: `gemini_client.py` (New — Shared Gemini Client)

```python
class GeminiImageClient:
    """
    Shared client for Gemini image and video generation APIs.

    Requires:
        - GEMINI_API_KEY env var or key file at src/conf/keys/gemini-api-key

    Ensures:
        - Manages Gemini client lifecycle
        - Tracks cost per generation
    """

    def __init__( self, resolution="1k", debug=False ):
        self.resolution = resolution
        self.debug      = debug
        self._client    = None  # Lazy init
        self.cost_total = 0.0

    def _get_client( self ):
        if self._client is None:
            from google import genai
            api_key = self._resolve_api_key()
            self._client = genai.Client( api_key=api_key )
        return self._client

    async def generate_image( self, prompt, output_path, **kwargs ) -> bool:
        """Generate image via Nano Banana 2 model."""
        client = self._get_client()
        response = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: client.models.generate_images(
                model  = "imagen-3.0-generate-002",  # Nano Banana 2 model ID
                prompt = prompt,
                config = { "number_of_images": 1 }
            )
        )
        # Save first image to output_path
        if response.generated_images:
            image = response.generated_images[ 0 ]
            image.image.save( output_path )
            self._track_cost()
            return True
        return False
```

**Note**: The exact model ID for Nano Banana 2 via Gemini API needs verification at implementation time. The `google-genai` SDK's `generate_images()` method is the entry point.

### Part B: `renderers/nano_banana.py`

```python
class NanoBananaRenderer( VisualRenderer ):
    SUPPORTED_TYPES = [ "hero_image", "infographic", "title_background", "icon" ]

    def __init__( self, gemini_client=None, debug=False, verbose=False ):
        self.gemini_client = gemini_client
        self.debug         = debug
        self.verbose       = verbose

    async def render( self, visual_type, visual_description, **kwargs ) -> Optional[ str ]:
        slide_title = kwargs.get( "slide_title", "" )
        output_dir  = kwargs.get( "output_dir" )
        slide_index = kwargs.get( "slide_index", 0 )

        if self.gemini_client is None: return None

        # 1. Build image generation prompt
        prompt = get_image_prompt( visual_type, visual_description, slide_title )

        # 2. Generate image
        output_filename = f"image-{slide_index:03d}.png"
        output_path     = os.path.join( output_dir, output_filename )
        success         = await self.gemini_client.generate_image( prompt, output_path )
        if not success: return None

        # 3. Return markdown image reference
        rel_path = os.path.join( "visuals", output_filename )
        return f"![{slide_title or 'Generated image'}]({rel_path})"
```

### Part C: `prompts/image_gen.py`

**Prompt engineering for slide images**:
- Title backgrounds: "Abstract professional background with soft gradients, theme: {colors}, style: modern minimal, no text"
- Hero images: "Conceptual illustration of {description}, professional style, clean composition"
- Infographics: "Clean infographic showing {description}, flat design, clear labels, {color palette}"
- Icons: "Simple flat icon representing {description}, single color, transparent background"

**Style modifiers** by visual_type:
- `hero_image` → "photorealistic, cinematic lighting"
- `infographic` → "flat design, vector style, clear text"
- `title_background` → "abstract, gradient, no text overlay"
- `icon` → "flat icon, single color, minimal"

### Part D: INI Configuration

```ini
# New keys in lupin-app.ini
presentation generator nano banana resolution = 1k
presentation generator nano banana style = professional
presentation generator image budget per presentation = 1.00
```

### Part E: Orchestrator Registration

```python
if not self.dry_run:
    gemini_client = GeminiImageClient( debug=self.debug )
    nano_banana = NanoBananaRenderer( gemini_client=gemini_client, debug=self.debug )
    registry.register( nano_banana )
```

---

## Nano Banana 2 API Pricing (March 2026)

| Resolution | Standard | Batch (50% off) |
|-----------|----------|-----------------|
| 0.5K | $0.045 | $0.022 |
| 1K | $0.067 | $0.034 |
| 2K | $0.101 | $0.050 |
| 4K | $0.151 | $0.076 |

**Default**: 1K resolution ($0.067/image) — good balance for slide decks.

## New Files

| Action | File | Est. Lines |
|--------|------|-----------|
| **Create** | `src/cosa/agents/presentation_generator/gemini_client.py` | ~150 |
| **Create** | `src/cosa/agents/presentation_generator/renderers/nano_banana.py` | ~100 |
| **Create** | `src/cosa/agents/presentation_generator/prompts/image_gen.py` | ~120 |
| **Modify** | `src/cosa/agents/presentation_generator/orchestrator.py` | +10 (registry + gemini client) |
| **Modify** | `src/cosa/agents/presentation_generator/renderers/__init__.py` | +2 (export) |
| **Modify** | `src/conf/lupin-app.ini` | +3 (config keys) |
| **Modify** | `src/conf/lupin-app-splainer.ini` | +3 (explanations) |
| **Create** | `src/tests/unit/test_presentation_nano_banana_renderer.py` | ~150 |

## Dependencies

| Dependency | Type | Status |
|-----------|------|--------|
| `google-genai` | pip | Already installed (v1.29.0) |
| Gemini API key | Credential | Needs to be provisioned + stored in `src/conf/keys/gemini-api-key` |

## Unit Tests (~20 tests)

| Class | Tests |
|-------|-------|
| `TestNanoBananaRenderer` | construction, SUPPORTED_TYPES, render with mock client |
| `TestGeminiImageClient` | construction, lazy init, cost tracking |
| `TestImagePrompt` | prompt builder for each visual_type, style modifiers, color injection |
| `TestRegistryIntegration` | NanoBananaRenderer registered for hero_image/infographic/title_background/icon |
| `TestErrorHandling` | API failure → None, rate limit, content filter rejection |

## Verification

1. `py_compile` on all new/modified files
2. Import chain: `from cosa.agents.presentation_generator.renderers.nano_banana import NanoBananaRenderer`
3. Unit tests: `pytest src/tests/unit/test_presentation_nano_banana_renderer.py -v`
4. Dry-run: PlaceholderRenderer used (NanoBananaRenderer disabled)
5. Live test: Submit presentation with title slide → verify PNG in `visuals/` dir
6. Cost check: Verify `gemini_client.cost_total` matches expected pricing

## Open Questions

1. **Gemini API key management**: Separate key from Claude API? Or shared Google Cloud credential?
2. **Model ID**: Exact Nano Banana 2 model identifier in Gemini API — verify at implementation time
3. **Content safety**: Nano Banana 2 has content filters. Strategy for rejected prompts?
4. **Aspect ratio**: Slides are 16:9. Should we request 16:9 images specifically?
5. **Batch API**: For presentations with many images, use batch endpoint for 50% savings?
