"""
WS3 — Layout-Parity Oracle: component-isolation browser-tier conftest.

These tiers (1–3, golden-replay) are :7999-eligible per the WS3 brief — DB-free,
read-only, <2 min — so they live in this SIBLING dir to deliberately NOT inherit
the e2e_ui DB-mutation guard (the session-autouse `verify_test_environment`
which requires lupin_db_test / :8000). A separate conftest = no DB check, so the
oracle's isolation tiers run on the dev server for fast iteration.

Carries the same deterministic-font Chromium launch args + locked
device-scale/viewport the e2e_ui visual suite uses, so Tier 2 (computed-style)
and Tier 3 (geometry, ±1px) stay stable across cold/warm/host/container runs.
See src/rnd/v0.1.6/2026.04.10-visual-regression-cold-warm-drift.md
"""

from __future__ import annotations

import pytest


@pytest.fixture( scope="session" )
def browser_type_launch_args( browser_type_launch_args ):
    """Deterministic font/color rendering (mirrors e2e_ui/conftest.py)."""
    return {
        **browser_type_launch_args,
        "args": [
            *browser_type_launch_args.get( "args", [] ),
            "--font-render-hinting=none",
            "--disable-lcd-text",
            "--force-color-profile=srgb",
            "--force-device-scale-factor=1",
        ],
    }


@pytest.fixture( scope="session" )
def browser_context_args( browser_context_args ):
    """Lock viewport + device scale so geometry (Tier 3) is reproducible."""
    return {
        **browser_context_args,
        "viewport": { "width": 1280, "height": 900 },
        "device_scale_factor": 1,
    }
