"""
WS3 — Full-Page Chrome Parity-Oracle: browser-tier conftest (lean, page-scoped).

Sibling to src/tests/parity_oracle/ (the sender-card oracle). These full-page
chrome tiers drive the LIVE served pages (`/app/notifications?classic=1` and
`/app/multiplexer`) directly — they do NOT mount the component-isolation harness
bundle, so unlike the sender-card conftest this one carries NO `_fresh_bundles`
build preamble (nothing to build; the dev server serves the pages). It keeps ONLY
the deterministic-font Chromium launch args + the locked device-scale/viewport the
visual suite uses, so Tier 2 (computed-style) and Tier 3 (geometry, ±1px) stay
stable across cold/warm/host/container runs.

Venue: :7999 — DB-free, read-only (loads a page + reads DOM), < 2 min → :7999-
eligible per CLAUDE.md §TESTING VENUES. A separate conftest (no DB check) means the
oracle runs on the dev server for fast iteration.
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
