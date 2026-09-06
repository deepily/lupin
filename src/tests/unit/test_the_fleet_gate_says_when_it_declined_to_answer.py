#!/usr/bin/env python3
"""
A GATE THAT FAILS OPEN MUST SAY SO — the cap's own silence, pinned.

🔴 THE INCIDENT (row `26f0cecf`, 2026-09-04). Two seats disagreed about whether the
fleet cap had refused. One measured a refusal at cap 8 / total 9, naming count and
split. Another watched the fleet go 10 to 12 while already over. **Neither account
could be checked**, because `default_fleet_gate` swallows every exception and returns
None: it allows the spawn, reaps nobody, and leaves no trace at any level.

⇒ The gate could not say "I did not refuse." An absence of refusals and an absence of
EVIDENCE of refusals are the same silence — this repo's own § AN EMPTY RESULT IS TWO
DIFFERENT FAILURES WEARING ONE FACE, arriving on a spawn gate.

=== WHAT THIS FILE DOES AND DOES NOT CLAIM ===

It pins that the branch NAMES ITSELF. It does **not** claim that branch ever fired in
production — nobody has shown it did, and by construction nobody now can for any moment
before this landed. Filed as a LATENT HAZARD, per María's correction 2026-09-04 21:34.

⚠️ THE BEHAVIOUR IS DELIBERATELY UNCHANGED, and the negative arm below is what pins
that. Fail-open here is a ruling with its reason in the source: a broken census that
refused every spawn would take the whole fleet down over a bridge-read error, while one
that allows lets the cap be briefly exceeded and the next spawn re-checks. Making it
fail CLOSED is a separate, HELD half of `26f0cecf` — it reverses that ruling, so it
belongs to María or Rick and waits on evidence this branch fires at all.
"""
import os
import sys

import pytest

_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from lupin_mcp import session_spawner


class _Config:
    def get( self, key, default=None, return_type="string", silent=False ):
        return { "cc session fleet size cap"         : 8,
                 "cc session fleet size cap maximum" : 18 }.get( key, default )


def _boom():
    raise RuntimeError( "bridge directory unreadable" )


def test_a_census_that_RAISES_still_allows_the_spawn( capsys ):
    """
    THE RULING, unchanged. An unreadable fleet is not evidence the fleet is full, so the
    gate returns None and the spawn proceeds. This arm is what makes the next one a
    finding about OBSERVABILITY rather than a silent behaviour change.
    """
    assert session_spawner.default_fleet_gate(
        1, config_fn=lambda: _Config(), census_fn=_boom ) is None, (
        "the fleet gate must fail OPEN on an unreadable census — that is a ruling with "
        "its reason in the source, not an omission"
    )


def test_the_gate_NAMES_the_exception_it_declined_on( capsys ):
    """
    🔴 THE ARM THIS FILE EXISTS FOR. The declining branch must identify itself and the
    error, so a later disagreement about whether the cap refused is ANSWERABLE.

    Delete the print and this reddens by name while the arm above stays green — which
    is what separates "the gate is silent" from "the gate allows".
    """
    session_spawner.default_fleet_gate( 1, config_fn=lambda: _Config(), census_fn=_boom )
    out = capsys.readouterr().out

    assert "[FLEET-CAP-GATE]" in out, (
        f"the declining branch must be identifiable in the log — saw: {out!r}"
    )
    assert "RuntimeError" in out, (
        f"it must name the exception TYPE, or the line says only that something went "
        f"wrong — saw: {out!r}"
    )
    assert "bridge directory unreadable" in out, (
        f"and the message, or the next reader cannot tell one failure from another — "
        f"saw: {out!r}"
    )
    assert "ALLOWED" in out, (
        f"and it must say the spawn was ALLOWED, because a log line that reports an "
        f"error without its consequence reads as a refusal — saw: {out!r}"
    )


def test_a_HEALTHY_census_prints_NOTHING( capsys ):
    """
    🔴 THE DISCRIMINATING NEGATIVE, and without it the arm above is satisfied by a gate
    that prints on every spawn. A line that always fires carries no information: the
    whole value of the notice is that its presence means something happened.
    """
    session_spawner.default_fleet_gate(
        1, config_fn=lambda: _Config(), census_fn=lambda: [] )
    assert "[FLEET-CAP-GATE]" not in capsys.readouterr().out, (
        "a gate that answered normally must say nothing — an always-on notice is noise"
    )


def test_a_BROKEN_logger_never_breaks_the_gate( monkeypatch ):
    """
    The belt on the belt. The notice is wrapped because a gate must never fail because
    its own logging did — that would convert an observability addition into an outage
    on the one path already known to be degraded.
    """
    def _print_explodes( *a, **k ):
        raise OSError( "stdout is gone" )

    monkeypatch.setattr( "builtins.print", _print_explodes )
    assert session_spawner.default_fleet_gate(
        1, config_fn=lambda: _Config(), census_fn=_boom ) is None, (
        "a failure inside the notice must not change what the gate returns"
    )


def quick_smoke_test():
    """Non-destructive: drive the declining branch once and read the notice."""
    import io, contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout( buf ):
        verdict = session_spawner.default_fleet_gate(
            1, config_fn=lambda: _Config(), census_fn=_boom )
    assert verdict is None
    assert "[FLEET-CAP-GATE]" in buf.getvalue()
    print( "✓ the gate names the exception it declined on, and still allows" )


if __name__ == "__main__":
    quick_smoke_test()
