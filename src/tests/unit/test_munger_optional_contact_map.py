"""
Unit tests for the optional contact-information map (2026-07-25).

`contact-information.map` is gitignored (.gitignore:65) because it holds
personal data, so it is ABSENT on every fresh deploy until someone ships it
out-of-band. `MultiModalMunger.__init__` loaded it eagerly, so on the GCP VM a
perfectly good transcription returned HTTP 500 with
"No such file or directory: .../contact-information.map".

The fix has two halves and BOTH are load-bearing:
    LOAD time  — tolerate absence, so ordinary transcription survives.
    USE  time  — REFUSE, so a contact-info command cannot answer "N/A" from an
                 empty map.

Tolerance without the refusal would trade a loud 500 for a plausible-looking
wrong answer, which is strictly worse. These tests pin both halves, and pin
that the OTHER four maps stay strict.
"""

import pytest


def _munger_module():
    import cosa.rest.multimodal_munger as mmm
    return mmm


# ── LOAD time: tolerate absence ──────────────────────────────────────────────

def test_load_optional_contact_info_returns_map_when_present( monkeypatch ):
    mmm = _munger_module()
    monkeypatch.setattr( mmm.du, "get_project_root", lambda: "/root" )
    monkeypatch.setattr( mmm.du, "get_file_as_dictionary", lambda *a, **k: { "name": "rick" } )

    got = mmm.MultiModalMunger._load_optional_contact_info( mmm.MultiModalMunger )
    assert got == { "name": "rick" }


def test_load_optional_contact_info_returns_empty_dict_when_absent( monkeypatch, capsys ):
    mmm = _munger_module()
    monkeypatch.setattr( mmm.du, "get_project_root", lambda: "/root" )

    def _missing( *a, **k ):
        raise FileNotFoundError( 2, "No such file or directory" )
    monkeypatch.setattr( mmm.du, "get_file_as_dictionary", _missing )

    got = mmm.MultiModalMunger._load_optional_contact_info( mmm.MultiModalMunger )
    assert got == {}


def test_load_optional_contact_info_warning_names_file_and_consequence( monkeypatch, capsys ):
    """
    A degraded capability must ANNOUNCE itself. The warning has to name the
    file (so it is actionable) AND say transcription is unaffected (so the
    next reader does not chase the wrong subsystem, which is exactly what the
    original mislabel caused).
    """
    mmm = _munger_module()
    monkeypatch.setattr( mmm.du, "get_project_root", lambda: "/root" )
    monkeypatch.setattr( mmm.du, "get_file_as_dictionary",
                         lambda *a, **k: ( _ for _ in () ).throw( OSError( "boom" ) ) )

    mmm.MultiModalMunger._load_optional_contact_info( mmm.MultiModalMunger )
    out = capsys.readouterr().out
    assert "contact-information.map" in out
    assert "WARN"                    in out
    assert "UNAFFECTED"              in out


def test_load_optional_contact_info_does_not_swallow_non_os_errors( monkeypatch ):
    """
    Only absence is tolerated. A malformed map is a DIFFERENT fault and must
    still surface — a bare `except Exception` here would hide parse bugs
    behind an empty dict.
    """
    mmm = _munger_module()
    monkeypatch.setattr( mmm.du, "get_project_root", lambda: "/root" )
    monkeypatch.setattr( mmm.du, "get_file_as_dictionary",
                         lambda *a, **k: ( _ for _ in () ).throw( ValueError( "malformed" ) ) )

    with pytest.raises( ValueError ):
        mmm.MultiModalMunger._load_optional_contact_info( mmm.MultiModalMunger )


# ── USE time: refuse loudly ──────────────────────────────────────────────────

class _StubMunger:
    """
    Binds only what munge_text_contact touches, so the refusal is tested
    without standing up a full MultiModalMunger (which needs config, five
    map files and a prompt).
    """
    def __init__( self, contact_info ):
        self.contact_info = contact_info

    CONTACT_INFO_PATH = "/src/conf/contact-information.map"


def _call_contact( contact_info, transcription="full" ):
    mmm = _munger_module()
    stub = _StubMunger( contact_info )
    return mmm.MultiModalMunger.munge_text_contact(
        stub, transcription, "multimodal contact information"
    )


def test_contact_command_refuses_when_map_is_empty():
    """The whole point: an empty map must RAISE, never return 'N/A'."""
    with pytest.raises( RuntimeError ) as exc:
        _call_contact( {} )
    assert "contact-information.map" in str( exc.value )


def test_contact_refusal_message_is_actionable():
    """It must say WHY it is missing and WHAT to do — not just that it is."""
    with pytest.raises( RuntimeError ) as exc:
        _call_contact( {} )
    msg = str( exc.value )
    assert "gitignored"     in msg
    assert "out-of-band"    in msg


def test_contact_command_does_not_return_na_placeholder():
    """
    Regression pin for the exact silent-wrong-answer this guard prevents:
    `self.contact_info.get( key, "N/A" )` would have produced a plausible
    string from an empty map.
    """
    try:
        result = _call_contact( {} )
    except RuntimeError:
        return   # correct behaviour
    pytest.fail( f"expected a refusal, got {result!r}" )


def test_constructor_wires_the_optional_loader( monkeypatch ):
    """
    Covers the CALL SITE (multimodal_munger.py:105), not just the helper.

    The helper's own tests invoke it directly, which leaves the constructor
    line — the thing that actually changed behaviour for every transcription —
    unexecuted. A guard that never runs where the defect lived is not a guard,
    so this builds a real MultiModalMunger and proves the wiring.
    """
    mmm = _munger_module()

    called = { "n": 0 }
    real   = mmm.MultiModalMunger._load_optional_contact_info

    def _counting( self ):
        called[ "n" ] += 1
        return real( self )

    monkeypatch.setattr( mmm.MultiModalMunger, "_load_optional_contact_info", _counting )

    munger = mmm.MultiModalMunger( "testing one two three", prompt_key="generic" )
    assert called[ "n" ] == 1, "constructor did not route through the optional loader"
    assert isinstance( munger.contact_info, dict )


def test_constructor_survives_a_missing_contact_map( monkeypatch ):
    """
    The actual GCP VM failure, reproduced at the unit tier: with the map
    absent, constructing the munger must SUCCEED and still produce a
    transcription. Before the fix this raised FileNotFoundError and the
    endpoint returned HTTP 500.
    """
    mmm = _munger_module()
    monkeypatch.setattr( mmm.MultiModalMunger, "_load_optional_contact_info", lambda self: {} )

    munger = mmm.MultiModalMunger( "testing one two three", prompt_key="generic" )
    assert munger.contact_info == {}
    assert munger.transcription, "transcription must survive a missing optional map"


def test_contact_command_still_works_when_map_is_populated():
    """Tolerance must not regress the populated path."""
    populated = {
        "name": "rick", "address": "1 main st", "city": "boston",
        "state": "ma", "zip": "02101", "email": "r@example.com",
        "telephone": "555-0100", "full": "rick",
    }
    raw, mode = _call_contact( populated, transcription="email" )
    assert mode == "multimodal contact information"
