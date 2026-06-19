"""
Multiplexer client-config endpoint.

Exposes display-tuning values that the multiplexer's `boot.ts` fetches once at
boot time and threads into the renderer (e.g., the `safeStringifyMeta` byte cap).
No PII; no auth required.

Authored 2026-05-06 for Phase 6a (jobs surface) F20 — `MAX_META_BYTES` cap is
sourced from `ConfigurationManager` INI rather than hardcoded into the bundle.
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from cosa.rest.dependencies.config import get_config_manager
from cosa.config.configuration_manager import ConfigurationManager


router = APIRouter( prefix="/api/multiplexer", tags=["multiplexer"] )


# ============================================================================
# Response model
# ============================================================================

class MultiplexerConfigResponse( BaseModel ):
    """
    Display-tuning values for the multiplexer front-end.

    Field names use snake_case to match server convention. Keys here become
    properties on the JSON object that `boot.ts` reads via
    `configureMetaDisplayCap(serverConfig)` per Phase 6a design F20.
    """
    multiplexer_max_meta_display_bytes: int
    # Lane E WP13 (F6) — INI default seed for the TTS preview-fraction slider.
    # The slider renderer layers a localStorage override on top of this default
    # (parity with notifications.js:791,804-811). Float in [0, 1]; default 0.25.
    tts_preview_fraction: float


# ============================================================================
# Endpoint
# ============================================================================

@router.get(
    "/config",
    response_model = MultiplexerConfigResponse,
    summary        = "Multiplexer client-config",
    description    = (
        "Returns display-tuning values that the multiplexer boot path fetches "
        "once at startup. Values are sourced from `ConfigurationManager` INI "
        "(`[Lupin: Baseline]` section). No auth required (no PII, no state)."
    )
)
async def get_multiplexer_config(
    config_mgr: ConfigurationManager = Depends( get_config_manager )
):
    """
    Return the multiplexer client-config payload.

    Requires:
        - `multiplexer max meta display bytes` is defined in lupin-app.ini
          `[Lupin: Baseline]` section (defaults to 256000 if missing).

    Ensures:
        - Returns MultiplexerConfigResponse with `multiplexer_max_meta_display_bytes`
          and `tts_preview_fraction`.
        - Defaults to 256000 / 0.25 respectively if the INI keys are unset.
    """
    max_meta_bytes = config_mgr.get(
        "multiplexer max meta display bytes",
        default     = 256000,
        return_type = "int"
    )

    # Lane E WP13 (F6) — TTS preview-fraction INI default seed (key shared with
    # the legacy /api/get-client-config payload at system.py:663-666).
    tts_preview_fraction = config_mgr.get(
        "tts preview fraction",
        default     = 0.25,
        return_type = "float"
    )

    return MultiplexerConfigResponse(
        multiplexer_max_meta_display_bytes = max_meta_bytes,
        tts_preview_fraction               = float( tts_preview_fraction )
    )


# ============================================================================
# Smoke Test
# ============================================================================

def quick_smoke_test():
    """Quick smoke test to validate router import + response model."""
    import cosa.utils.util as du

    du.print_banner( "Multiplexer Config Router Smoke Test", prepend_nl=True )

    try:
        # Test 1: Router imports cleanly
        print( "Testing router import..." )
        assert router is not None
        assert router.prefix == "/api/multiplexer"
        print( "✓ Router imported successfully" )

        # Test 2: Response model accepts the expected field
        print( "\nTesting MultiplexerConfigResponse model..." )
        resp = MultiplexerConfigResponse(
            multiplexer_max_meta_display_bytes=256000,
            tts_preview_fraction=0.25
        )
        assert resp.multiplexer_max_meta_display_bytes == 256000
        assert resp.tts_preview_fraction == 0.25
        print( "✓ MultiplexerConfigResponse works" )

        # Test 3: Listed endpoints
        print( "\nRegistered endpoints:" )
        for route in router.routes:
            print( f"  {route.methods} {route.path}" )

    except Exception as e:
        print( f"✗ Error: {e}" )
        import traceback
        traceback.print_exc()

    print( "\n✓ Multiplexer config router smoke test completed" )


if __name__ == "__main__":
    quick_smoke_test()
