"""
The DM tutor must SAY SO when a rewrite is one the reader may not be able to attribute.

⚠️ IT USED TO REFUSE, AND STOPPED ON 2026-08-26 (row `20026f56`, Rick's ruling). Refusing
sent the sender's full uncondensed original on 53-58% of every rewrite; the harm it was
buying off was three peer reports in three weeks, each one caught by the human reading it.
So the rewrite goes out now, the check still runs, the reason is still written to the row,
and the recipient gets four extra words telling them to check who did what. The tests
below were rewritten from "refuses" to "flags and delivers" in the same change — if you
are looking for the old behaviour, it is in git, not in a config switch.

Row `cf1587cd`, filed by María 🌸 on Clayton 😎's finding, 2026-08-25. Four condensed
DMs reached her in six minutes; in two she could not tell whose measurement a claim was
about, and a third was inverted far enough that Clayton apologised for an ambiguity the
transport had made rather than him.

THE FIXTURES BELOW ARE THOSE MESSAGES. They are the real submitted and delivered bodies
from thread `b3abbb72`, lifted verbatim out of the traffic corpus — not paraphrases and
not invented examples. `MARIA_2156` is the one she opened the row with.

REVERT AND WATCH IT GO RED (bar item 4): deleting the `_dropped_attribution` call in
`_apply_dm_tutor` turns `test_send_path_flags_and_delivers_marias_2156_message` red on
that exact message — the outcome reads `rewritten` and the row carries no reason, which
is the instrument going dark rather than a defect being fixed. Recorded in
`src/rnd/v0.2.0/2026.08.26-dm-condenser-drops-sentence-subjects.md` §3.

Sibling file: `test_dm_tutor_attribution_guard.py` covers row `897a8db1` — the tutor
INVENTING who holds a position. That guard lives in `dm_tutor/tutor.py` and is a
different half of the same surface; see §4 of the doc for why it is not wired in here.
"""
import pytest

from cosa.rest.routers.dm import (
    _DM_TUTOR_DEFAULTS,
    _apply_dm_tutor,
    _attribution_prose,
    _count_attributions,
    _dropped_attribution,
    _attribution_personas,
)


# ── The real messages from thread b3abbb72 ───────────────────────────────────

MARIA_2156_SUBMITTED = (
    "Your `$$` correction lands on ME, not just on the announcement — so I re-derived "
    "rather than reasoned about it.\n\n"
    "I used the exported per-shell form tonight and then quoted a coverage figure off "
    "it. Each of my runs happened to be a separate shell, so `$$` differed and nothing "
    "clobbered — but \"happened to be\" is not a property I should be resting a number "
    "on, which is your whole point. Re-ran it under `COVERAGE_FILE=$(mktemp -u ...)`, "
    "per-run: canonical_command still reads zero missing lines and zero missing "
    "branches.\n\n"
    "All of it is in my memento with your mktemp form as the default and the export "
    "form marked per-shell-only. Good night."
)
MARIA_2156_DELIVERED = (
    "The method used to derive the coverage figure was unreliable and needed to be "
    "re-run using a more reliable method.\n"
    "The initial method involved exporting a variable per shell, which led to different "
    "values for `$$` and did not cause any overwriting of data.\n"
    "The author re-ran the process using `mktemp` to ensure the coverage figure's "
    "accuracy and noted a limitation in the method used to check if a file path is "
    "unique."
)

ROLE_NOUN_SUBMITTED = (
    "Agreed, and not doing it tonight is the right call — reshaping a checklist at "
    "21:54 on a half-worked idea is how a document stops being trusted.\n\n"
    "One thing I could not act on: your last line read \"coverage data_file defect\" "
    "with no context — if that was a pointer at something you want looked at, send it "
    "as its own message tomorrow and I will take it."
)
ROLE_NOUN_DELIVERED = (
    "The author requests clarification on the \"coverage data_file defect\" mentioned "
    "in the last line.\n"
    "They agree not to work on the checklist at 21:54 to maintain trust in the document."
)

# The same message condensed WITHOUT losing who it is about — what a passing rewrite
# looks like, so the guard is shown to discriminate rather than merely to fire.
MARIA_2156_DELIVERED_OK = (
    "Your `$$` correction landed on me, so I re-derived my coverage figure rather than "
    "reasoning about it.\n"
    "I had quoted it off an exported per-shell COVERAGE_FILE; re-run under mktEMP "
    "per-run, canonical_command still reads zero missing lines and branches.\n"
    "Your deeper point stands: the guard refuses when UNSET and cannot tell whether the "
    "value is unique."
)


# ── The predicate ────────────────────────────────────────────────────────────

def test_refuses_marias_2156_message():
    """The message the row was opened with is refused."""
    reason = _dropped_attribution( MARIA_2156_SUBMITTED, MARIA_2156_DELIVERED )
    assert reason, "the 21:56 message must not be delivered as condensed"
    assert "dropped" in reason
    assert "rewrite 0x" in reason


def test_refuses_the_2154_message():
    """The 21:54 message from the same thread is refused — it kept no person at all."""
    reason = _dropped_attribution( ROLE_NOUN_SUBMITTED, ROLE_NOUN_DELIVERED )
    assert reason, "the 21:54 message must not be delivered as condensed"


def test_refuses_a_role_noun_that_names_nobody():
    """
    "The developer" in place of a person is refused ON ITS OWN — the rewrite here KEEPS
    a person, so the dropped-attribution branch cannot fire and only the role noun can.
    A test that lets both branches fire proves neither.
    """
    original = (
        "You asked who ran it and I did, twice, against your branch and then against "
        "mine. Rio watched the second one."
    )
    rewritten = (
        "The developer ran it twice, against both branches.\n"
        "You have the second run's output already."
    )
    reason = _dropped_attribution( original, rewritten )
    assert reason
    assert "role noun" in reason
    assert "developer" in reason.lower()


def test_passes_a_rewrite_that_keeps_the_people():
    """A rewrite carrying the same claims WITH their subjects is delivered."""
    assert _dropped_attribution( MARIA_2156_SUBMITTED, MARIA_2156_DELIVERED_OK ) == ""


def test_one_passing_mention_is_below_the_threshold():
    """
    A body that mentions a person once can lose the mention without costing the reader
    anything — the threshold is why the guard does not refuse every impersonal summary.
    """
    original  = "I looked at the queue depth. It sat at 4 all afternoon and never moved."
    rewritten = "The queue depth sat at 4 all afternoon and never moved."
    assert _dropped_attribution( original, rewritten, min_persons=3 ) == ""
    assert _dropped_attribution( original, rewritten, min_persons=1 ) != ""


def test_a_restored_path_is_not_an_attribution():
    """
    ⚠️ THE MISS THIS PINS. `_restore_dropped_pointers` appends a path line, and a
    memento filename carries a persona name inside it — so a rewrite that threw every
    person away scored as ATTRIBUTED because of the filename underneath it.
    """
    original = (
        "You asked whether my memento survives the reap and I checked rather than "
        "assuming. My own file verifies clean, and I re-read yours as well."
    )
    rewritten = (
        "The memento verifies clean and survives the reap.\n"
        "Nothing in the record was lost.\n"
        ".claude-memento-cheech-80c17315.md"
    )
    prose = _attribution_prose( rewritten )
    assert "cheech" not in prose.lower(), "the pointer line must not be read as prose"
    assert _dropped_attribution( original, rewritten ) != ""


def test_personas_come_from_the_live_voice_pool():
    """The roster is read from config, not hardcoded, so a new persona is recognised."""
    personas = _attribution_personas()
    assert personas, "the voice pool must be readable"
    assert "maria" in personas


def test_counting_sees_pronouns_and_names():
    """The count is what the threshold is applied to, so it is pinned directly."""
    assert _count_attributions( "I asked you about it", [ "maria" ] ) == 2
    assert _count_attributions( "Maria and Rio ran it", [ "maria", "rio" ] ) == 2
    assert _count_attributions( "the queue drained", [ "maria" ] ) == 0


def test_an_unreadable_roster_costs_recall_and_never_correctness( monkeypatch ):
    """
    A config failure must not take the guard out. It degrades to pronouns only, which
    refuses MORE (a rewrite keeping just a name now looks person-free) and never less.
    """
    monkeypatch.setattr( "cosa.config.configuration_manager.ConfigurationManager",
                         lambda *a, **k: ( _ for _ in () ).throw( RuntimeError( "ini gone" ) ) )
    assert _attribution_personas() == []


def test_an_unreadable_counter_leaves_the_text_alone( monkeypatch ):
    """
    If the claim counter cannot be imported the guard reads the raw text rather than
    nothing — a degraded reading, not a disabled check.
    """
    import cosa.agents.dm_tutor.sentences as sentences

    def explode( *args, **kwargs ):
        raise RuntimeError( "counter unavailable" )

    monkeypatch.setattr( sentences, "prose_lines", explode )
    raw = "You asked and I answered.\nsrc/cosa/rest/routers/dm.py"
    assert _attribution_prose( raw ) == raw


def test_counting_returns_zero_rather_than_raising():
    """A malformed roster reads as "nobody named", never as an exception on the send path."""
    assert _count_attributions( "I asked you about it", None ) == 0


def test_the_guard_never_raises( monkeypatch ):
    """
    FAIL-SOFT: a broken guard delivers the rewrite rather than blocking every DM in the
    fleet. Proven by breaking it rather than by asserting the try/except is present.
    """
    import cosa.rest.routers.dm as dm

    def explode( *args, **kwargs ):
        raise RuntimeError( "guard is broken" )

    monkeypatch.setattr( dm, "_attribution_personas", explode )
    assert dm._dropped_attribution( MARIA_2156_SUBMITTED, MARIA_2156_DELIVERED ) == ""


# ── The send path ────────────────────────────────────────────────────────────

def _config( **overrides ):
    """
    The tutor config the send path reads, with the guard on by default.

    ⚠️ SEEDED FROM `_DM_TUTOR_DEFAULTS`, not from a hand-written literal — the same
    lesson `test_dm_tutor_send_path._cfg` records. The send path indexes its config
    directly, so a hand-written dict missing a newly-added key raises KeyError inside
    `_apply_dm_tutor`, which catches it and delivers the ORIGINAL; every "the tutor
    fired" test then fails with an assertion about delivered text that names nothing
    about config. It happened here when `product_names` was added (row f3d96537).
    """
    config = dict( _DM_TUTOR_DEFAULTS )
    config.update( {
        "enabled"                 : True,
        "trigger_claims"          : 1,
        "gate_enabled"            : False,
        "gate_max_claims"         : 4,
        "fab_guard_strict"        : True,
        "attribution_guard"       : True,
        "attribution_min_persons" : 3,
    } )
    config.update( overrides )
    return config


def test_send_path_flags_and_delivers_marias_2156_message():
    """
    🔴 THE REVERT-AND-WATCH-IT-GO-RED TEST (bar item 4), and now the OPEN-GATE test too.

    Both halves are asserted on one message, deliberately, because the whole risk of row
    `20026f56` is that somebody satisfies one half and quietly drops the other:

      the gate is OPEN    — the condensed rewrite is what goes out, not the original
      the sensor is LIVE  — the row still names the outcome and still says why

    Delete the `_dropped_attribution` block in `_apply_dm_tutor` and the second half goes
    red on the exact message María opened the row with.
    """
    from cosa.rest.routers.dm import DM_TUTOR_ATTRIBUTION_NOTICE

    delivered, meta = _apply_dm_tutor(
        MARIA_2156_SUBMITTED,
        config=_config(),
        rewrite_fn=lambda body: MARIA_2156_DELIVERED,
    )
    # THE GATE IS OPEN.
    assert delivered != MARIA_2156_SUBMITTED, "the rewrite must go out, not the original"
    assert delivered.startswith( MARIA_2156_DELIVERED.split( "\n" )[ 0 ] )
    assert delivered.endswith( DM_TUTOR_ATTRIBUTION_NOTICE )

    # THE SENSOR IS LIVE.
    assert meta[ "tutor_outcome" ]  == "attribution_flagged"
    assert meta[ "tutor_attribution" ]
    assert "dropped" in meta[ "tutor_attribution" ]


def test_send_path_delivers_a_rewrite_that_keeps_the_people():
    """
    The clean case, and the half of Part B that is easy to lose.

    🔴 THE WARNING MUST NOT BECOME WALLPAPER. Roughly half of rewrites keep everybody the
    sender named. If "check who did what" is appended to those too, it is read past
    everywhere and therefore read past on the ones that lost a name — which is the only
    place it does anything. So this pins the PLAIN notice on an attributable rewrite.
    """
    from cosa.rest.routers.dm import DM_TUTOR_NOTICE, DM_TUTOR_ATTRIBUTION_NOTICE

    delivered, meta = _apply_dm_tutor(
        MARIA_2156_SUBMITTED,
        config=_config(),
        rewrite_fn=lambda body: MARIA_2156_DELIVERED_OK,
    )
    assert meta[ "tutor_outcome" ]     == "rewritten"
    assert meta[ "tutor_attribution" ] is None
    assert delivered.startswith( MARIA_2156_DELIVERED_OK.split( "\n" )[ 0 ] )
    assert delivered.endswith( DM_TUTOR_NOTICE )
    assert DM_TUTOR_ATTRIBUTION_NOTICE not in delivered


def test_send_path_honours_the_off_switch():
    """
    With the check off the rewrite still goes out — and now carries the PLAIN notice and
    an empty row, because nothing measured it. That is the difference between "the check
    said this one is fine" and "nobody looked", and the corpus has to keep them apart.
    """
    from cosa.rest.routers.dm import DM_TUTOR_NOTICE, DM_TUTOR_ATTRIBUTION_NOTICE

    delivered, meta = _apply_dm_tutor(
        MARIA_2156_SUBMITTED,
        config=_config( attribution_guard=False ),
        rewrite_fn=lambda body: MARIA_2156_DELIVERED,
    )
    assert meta[ "tutor_outcome" ]     == "rewritten"
    assert meta[ "tutor_attribution" ] is None
    assert delivered.startswith( MARIA_2156_DELIVERED.split( "\n" )[ 0 ] )
    assert delivered.endswith( DM_TUTOR_NOTICE )
    assert DM_TUTOR_ATTRIBUTION_NOTICE not in delivered


def test_send_path_honours_the_threshold():
    """The threshold reaches the send path, not just the predicate."""
    original  = "I looked at the queue depth. It sat at 4 all afternoon and never moved."
    rewritten = "The queue depth sat at 4 all afternoon and never moved."

    _, lenient = _apply_dm_tutor( original, config=_config( attribution_min_persons=3 ),
                                  rewrite_fn=lambda body: rewritten )
    _, strict  = _apply_dm_tutor( original, config=_config( attribution_min_persons=1 ),
                                  rewrite_fn=lambda body: rewritten )
    assert lenient[ "tutor_outcome" ] == "rewritten"
    assert strict[ "tutor_outcome" ]  == "attribution_flagged"


def test_meta_carries_the_field_on_every_path():
    """
    A null must mean "the reader could attribute this one", never "this row predates
    the guard" — which is why the corpus schema version moved with it.
    """
    from cosa.rest.routers.dm import DM_CORPUS_SCHEMA_VERSION

    # 6, not 5: `attribution_flagged` replaced `attribution_blocked` and old rows were
    # deliberately NOT migrated, so the version is what tells a reader which of the two
    # a row is allowed to carry.
    assert DM_CORPUS_SCHEMA_VERSION >= 6
    _, off = _apply_dm_tutor( "one short line.", config=_config( enabled=False ),
                              rewrite_fn=lambda body: "x" )
    assert "tutor_attribution" in off
    assert off[ "tutor_attribution" ] is None
