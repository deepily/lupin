"""
The wake must say that `stable_session_id` will MATCH and proves nothing.

Row 864e2c28, found 2026-09-03 by Mr. Radio 🦉 while executing a real wake on his own
pane, and verified independently against the artifacts of that fire.

⚠️ THE WAKE WAS NEVER QUOTING THE WRONG FIELD. Its chain extracts the bridge's TRANSIENT
`session_id` with an anchored grep that cannot match the `stable_session_id` line, so the
field it names and the value it quotes have always agreed. The trap is STRUCTURAL and it
is confined to a pane's FIRST clear: until a pane clears once, `session_id` and
`stable_session_id` hold the SAME value (register_session: "On first start,
stable_session_id == session_id... On subsequent lifecycle events (compact, clear), they
diverge"). So the quoted id matches BOTH fields, and a reader who reaches for "the field
whose value equals the id I was given" — the natural move on an exact string match —
lands on the one field that CANNOT discriminate a clear, and gets a confident wrong
answer plus a dispute file.

⇒ Because the two fields hold ONE value at that moment, no choice of quoted value can
separate them. A sentence is the only remedy available, which is why this is guarded as
prose rather than as behaviour.

🔴 WHY THE EXISTING SUITE COULD NOT SEE THIS. `test_the_wake_hands_the_seat_an_oracle_it
_cannot_author` asserts `"claude_code.session_id" in txt`. That PASSES on the trapped text
and on the fixed text alike — the wake always named the right field. An assertion that is
already true cannot notice a missing warning, so the guard below asserts the thing that
was ABSENT, not the thing that was present.
"""
import lupin_mcp.self_respin_core as sr


def _txt():
    return sr.build_wake_text( "/m/memento.md", "nonce-7", "/p/proof.marker" )


def test_the_wake_names_the_field_that_will_match_and_cannot_decide():
    txt = _txt()
    assert "stable_session_id" in txt, (
        "the wake never mentions stable_session_id, so a reader matching on the field "
        "whose VALUE equals the quoted id has nothing warning them off it"
    )


def test_the_wake_says_that_field_proves_nothing():
    """Naming it is not enough — named without a verdict, it reads like a second oracle."""
    low = _txt().lower()
    assert "proves nothing" in low, \
        "stable_session_id is named but the wake never says it cannot decide"


def test_the_wake_still_names_session_id_as_the_one_that_decides():
    """NEGATIVE CONTROL. The warning must not cost the wake its actual instrument."""
    txt = _txt()
    assert "claude_code.session_id" in txt
    assert "get_session_info" in txt


def test_the_warning_survives_the_chain_substitution():
    """The sentence sits next to the sentinel, so a substitution must not eat it."""
    txt = _txt().replace( sr._PRE_CLEAR_SID_SENTINEL, "11111111-2222-3333-4444-555555555555" )
    assert "stable_session_id" in txt and "proves nothing" in txt.lower()
    assert "\n" not in txt, "the wake is typed with send-keys -l plus one Enter"
