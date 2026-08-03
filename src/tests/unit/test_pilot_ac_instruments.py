"""
§D — BEFORE YOU AUDIT WHAT A CHECK COVERS, AUDIT WHETHER IT RUNS.

Design: src/rnd/v0.1.9/2026.07.13-vertex-model-garden-toggle-search-and-logging.md §6a

WHY THIS FILE EXISTS
--------------------
`src/terraform/tests/modules.bats` held FIFTEEN security assertions that had never
executed even once: `bats` is not installed and nothing invoked it. They read like a
guard, they were cited like a guard, and they enforced nothing. The lesson generalizes,
and it is the governing law of §D:

    A check that cannot run is WORSE than no check, because it radiates false
    confidence. Absence of a red is not evidence of correctness when no assertion
    ever executed.

§6a rests its entire pilot on ONE claim: Cloud Monitoring `PublisherModel` is a SOUND,
INDEPENDENT oracle. AC-D4, AC-D4b ("the single most valuable AC in the document"),
AC-D8 and AC-D9a all ride it; AC-D7 rides BigQuery. So before anyone writes those ACs,
somebody has to ask the question nobody asked about bats:

    ⚠️  IS THE INSTRUMENT ACTUALLY INSTALLED?

VERIFIED ON THIS HOST, 2026-07-13:

    google.cloud.monitoring_v3  ***ABSENT***   ← the sound oracle's client library
    google.cloud.bigquery       ***ABSENT***   ← AC-D7's client library
    bq CLI / gcloud             present        ← so AC-D7 HAS a path
    google.auth / requests      present        ← so the Monitoring REST path is open

Both client libraries are missing. The trap this file exists to spring shut: the
idiomatic way to write a test against a missing library is `pytest.importorskip(...)`
or `try: import … except ImportError: skip`. Do that here and AC-D4/D7/D8 become
SKIPS — and a skip is invisible in a 9,131-test run. That is modules.bats, reincarnated
inside the acceptance criteria the pilot's credibility rests on, in the very cascade
convened to kill that disease.

    We would have verified a METERED-BILLING pilot with assertions that never ran.

So the rule below is structural, not advisory, and it is enforced by a test rather than
by a paragraph — because §6b's whole lesson is that a MUST in a markdown table is not a
mechanism.

Venue: :7999-eligible — importlib probes + file reads. No network, no GCP call, no
mutation, no spend.
"""
import importlib.util
import os
import re
import shutil

import pytest

import cosa.utils.util as cu
from cosa.utils.vertex_env import CERTIFIED_VERTEX_REGIONS

PROJECT_ROOT = cu.get_project_root()


# ── the instrument register ───────────────────────────────────────────────────────
#
# Each pilot AC, the oracle §6a assigns it, and the instrument that oracle needs. This
# is a COVERAGE list (it rots by omission), so it is pinned against the design doc by
# test_every_pilot_ac_in_the_design_doc_is_registered() below — the guard that guards
# the list, because an unguarded coverage list is exactly how OSQ D-2 went missing.
#
# `instrument_present` is the load-bearing column, and its name is EXACT ON PURPOSE.
#
# ⚠️  IT MEANS "THE TOOL IS ON THIS HOST." IT DOES NOT MEAN "THIS AC CAN PRODUCE A
#     VERDICT." Instrument-present is NECESSARY, NEVER SUFFICIENT.
#
# The field was called `runnable_now` for its first draft, and that name was a LIE for
# AC-D5/AC-D7/AC-D9b: `bq` is on $PATH, but the BigQuery sink may not exist and logging
# may not be configured, so those ACs can still be INADMISSIBLE with a perfectly healthy
# instrument. Calling that "runnable" would have re-committed the founding sin of this
# whole cascade — A NAME IS NOT THE THING ITSELF (§7 lesson 0: we read a metadata 200 as
# "SERVED" and pinned the region SSOT to a region that cannot serve).
#
# So: an ABSENT instrument proves an AC is INADMISSIBLE. A PRESENT one proves only that
# the AC is not disqualified for THIS reason. INADMISSIBLE is a third verdict, distinct
# from both pass and fail (F-D18: "search didn't fire" ≠ "we cannot see") — and an AC
# whose instrument is absent may NEVER be reported as passing.
PILOT_ACS = {
    "AC-D0":  { "oracle": "human attestation (billing export — console-only)",
                "needs": None,                        "instrument_present": True  },
    "AC-D0b": { "oracle": "rawPredict -> 200 (region certification)",
                "needs": "gcloud",                    "instrument_present": True  },
    "AC-D1":  { "oracle": "pytest over --dry-run env composition",
                "needs": None,                        "instrument_present": True  },
    "AC-D2":  { "oracle": "pytest red-first on every guard",
                "needs": None,                        "instrument_present": True  },
    "AC-D3":  { "oracle": "headless `claude -p` -> exit 0",
                "needs": None,                        "instrument_present": True  },
    "AC-D3a": { "oracle": "fetchPublisherModelConfig -> 200",
                "needs": "gcloud",                    "instrument_present": True  },
    "AC-D4":  { "oracle": "Cloud Monitoring PublisherModel model_invocation_count",
                "needs": "google.auth",                "instrument_present": True  },
    "AC-D4b": { "oracle": "Cloud Monitoring PublisherModel `location` resource label",
                "needs": "google.auth",                "instrument_present": True  },
    "AC-D5":  { "oracle": "web-search tool-use block in the BQ-logged request",
                "needs": "bq",                         "instrument_present": True  },
    "AC-D6":  { "oracle": "cosa-voice get_session_info() round-trip",
                "needs": None,                        "instrument_present": True  },
    "AC-D7":  { "oracle": "bq query -> SELECT COUNT(*) > 0, schema-agnostic",
                "needs": "bq",                         "instrument_present": True  },
    "AC-D8":  { "oracle": "process-env check (primary) + Monitoring canary (secondary)",
                "needs": "google.auth",                "instrument_present": True  },
    "AC-D9a": { "oracle": "Monitoring input/output_token_size x rate card",
                "needs": "google.auth",                "instrument_present": True  },
    "AC-D9b": { "oracle": "billing-export BigQuery dataset, T+24h",
                "needs": "bq",                         "instrument_present": True  },
}

# The GCP client libraries §6a's oracles would idiomatically be written against, and
# which are NOT INSTALLED. Any test that reaches for one of these behind a skip is a
# dead assertion.
ABSENT_ORACLE_LIBRARIES = ( "google.cloud.monitoring_v3", "google.cloud.bigquery" )

DESIGN_DOC = "src/rnd/v0.1.9/2026.07.13-vertex-model-garden-toggle-search-and-logging.md"

# Ids that appear in the doc's PROSE but are NOT acceptance criteria. Every entry carries a
# reason, and the SET IS PINNED below — an unexplained exclusion is how a real AC would hide
# from the register, and "widening a predicate widens what it lets in."
PROSE_SHORTHAND = {
    "AC-D9": "§9 prose shorthand for the AC-D9a/AC-D9b PAIR — §6a's table defines only a+b, "
             "never a bare AC-D9. Reported to the doc owner; not a distinct AC and has no oracle.",
}


def _available( instrument ):
    """Is this instrument actually present on THIS host? (the question nobody asked bats)"""
    if instrument is None:                 return True
    if "." in instrument:                  return importlib.util.find_spec( instrument ) is not None
    return shutil.which( instrument ) is not None


def _read( rel_path ):
    with open( os.path.join( PROJECT_ROOT, rel_path ), "r", errors="replace" ) as f:
        return f.read()


def references_absent_library( body ):
    """
    Does this source reach for one of the absent GCP oracle libraries — in ANY spelling?

    🔴 THIS FUNCTION EXISTS BECAUSE MY FIRST VERSION OF THE BAN WAS DECORATIVE, and only
    a red-first falsification found it. The original pre-filter tested `"google.cloud.bigquery"
    in body` — the DOTTED string. But the idiomatic import is:

        from google.cloud import bigquery          # <-- contains no dotted string

    so a test hidden behind `try/except ImportError` around that line sailed straight
    through the ban built to catch it. The guard against dead checks was ITSELF partially
    dead, in the same file that lectures about dead checks, written by the person who had
    just deleted 15 dead checks. Defects cluster inside fixes, in the glow of an accepted
    finding — so both spellings are matched, and both are proven RED by the committed
    fixtures below.
    """
    hits = []
    for lib in ABSENT_ORACLE_LIBRARIES:
        package, _, module = lib.rpartition( "." )        # google.cloud . bigquery
        dotted   = re.escape( lib )                                              # google.cloud.bigquery
        from_form = r"from\s+{pkg}\s+import\s+[^\n]*\b{mod}\b".format(
            pkg=re.escape( package ), mod=re.escape( module ) )                  # from google.cloud import bigquery
        if re.search( dotted, body ) or re.search( from_form, body ):
            hits.append( lib )
    return hits


# The ways a test can reach for a library while NOT failing when it is missing. Each of
# these turns an absent-instrument error into an invisible non-execution.
SKIP_IDIOMS = (
    re.compile( r"""importorskip\(\s*["']""" ),
    re.compile( r"""except\s+ImportError""" ),
    re.compile( r"""find_spec\(""" ),
)


def is_dead_check( body ):
    """
    Does this source reach for an ABSENT oracle library in a way that SKIPS instead of
    failing? That is the precise shape of a dead check — and it is a pure predicate, so
    the offender path is exercised by committed fixtures rather than only by the accident
    of a dirty tree. (A clean tree never executes an offender branch, which is how the
    detection logic in a guard rots unnoticed.)
    """
    if not references_absent_library( body ): return False
    return any( idiom.search( body ) for idiom in SKIP_IDIOMS )


# COMMITTED red-first fixtures for the dead-check predicate itself.
_DEAD_CHECK_FIXTURES = [
    ( 'mon = pytest.importorskip("google.cloud.monitoring_v3")',                   True  ),
    ( "try:\n    from google.cloud import bigquery\nexcept ImportError:\n    pass", True  ),
    ( "if find_spec( 'google.cloud.monitoring_v3' ):\n    pass",                    True  ),
    # honest + unconditional: fails LOUD when the lib is missing. Exactly what we want.
    ( "from google.cloud import monitoring_v3\nclient = monitoring_v3.Client()",    False ),
    ( "import requests  # REST path — no absent lib at all",                        False ),
    # a skip idiom around a library that IS installed is none of this guard's business
    ( 'pytest.importorskip( "numpy" )',                                             False ),
]


@pytest.mark.parametrize( "body,expected", _DEAD_CHECK_FIXTURES )
def test_dead_check_predicate_bites_on_skips_and_spares_honest_imports( body, expected ):
    """Red-first, committed. An unconditional import is ALLOWED — failing loud on a missing
    instrument is the entire point. Only the SKIP idioms are banned."""
    assert is_dead_check( body ) is expected


# ── the law ───────────────────────────────────────────────────────────────────────

# COMMITTED red-first fixtures for the spelling bug that made the ban decorative. The
# `from X import Y` row is the one that shipped GREEN on a real violation until a
# falsification pass caught it — it stays here forever so the hole cannot silently
# reopen.
_ABSENT_LIB_FIXTURES = [
    ( 'mon = pytest.importorskip("google.cloud.monitoring_v3")', [ "google.cloud.monitoring_v3" ] ),
    ( "from google.cloud import bigquery",                       [ "google.cloud.bigquery" ] ),
    ( "from google.cloud import monitoring_v3",                  [ "google.cloud.monitoring_v3" ] ),
    ( "client = google.cloud.bigquery.Client()",                 [ "google.cloud.bigquery" ] ),
    ( "import requests, google.auth",                            [] ),
    ( "# we deliberately use the REST path instead",             [] ),
]


@pytest.mark.parametrize( "body,expected", _ABSENT_LIB_FIXTURES )
def test_references_absent_library_catches_every_import_spelling( body, expected ):
    """The dotted form AND the `from google.cloud import X` form. Missing the second one
    is what made the skip-ban decorative on its first draft."""
    assert references_absent_library( body ) == expected

def register_drift( ac, spec ):
    """
    Does this register entry disagree with the HOST? Returns a reason, or None.

    Pure, so BOTH directions are exercised by fixtures. Every AC currently declares
    instrument_present=True (the Monitoring four were re-pointed at the REST oracle), so
    the "declared absent" branch is unreachable from real data — and an unreachable branch
    is an untested branch is a branch that rots. Testing it directly is the alternative to
    a `# pragma: no cover`, which would have hidden exactly that.
    """
    have = _available( spec[ "needs" ] )

    if spec[ "instrument_present" ] and not have:
        return (
            f"{ac} is declared instrument_present=True but its instrument '{spec[ 'needs' ]}' is "
            f"NOT INSTALLED. Its oracle ({spec[ 'oracle' ]}) CANNOT PRODUCE A VERDICT. Install the "
            f"instrument, re-point the AC at one that exists, or flip the flag — but do NOT leave "
            f"an AC that cannot run while the plan believes it can. That is exactly how fifteen "
            f"terraform security assertions ran zero times."
        )

    if not spec[ "instrument_present" ] and have:
        return (
            f"GOOD NEWS, AND THIS RED IS THE MESSAGE: {ac}'s instrument '{spec[ 'needs' ]}' is NOW "
            f"INSTALLED, but the register still says instrument_present=False. Flip it to True and "
            f"WRITE THE AC ({spec[ 'oracle' ]}) — an oracle just became available and the plan does "
            f"not know it yet."
        )

    return None


# host_only (row dba10ba5): this function's name is not decoration — its SUBJECT is the
# host. In a container `gcloud`/`bq` are absent, so it goes red for a claim that was
# never about the container; install them there and it goes GREEN while the proposition
# ("the operator host carries them") stays unverified. Neither outcome is a verdict, so
# where the host is unreachable it is deselected AND NAMED rather than silenced. On the
# host — the only venue that can judge it — nothing changes and it still fails loudly.
@pytest.mark.host_only
@pytest.mark.parametrize( "ac", sorted( PILOT_ACS ) )
def test_every_ac_register_entry_matches_the_host( ac ):
    """
    An AC declared runnable MUST have a working instrument — and one declared NOT runnable
    must genuinely lack one. Both directions, and NOTHING here skips.

    A skip would be self-refuting in this file of all files: I would be papering over an
    unrunnable AC with the exact mechanism (an invisible non-execution) that let fifteen
    terraform assertions enforce nothing for months.
    """
    assert register_drift( ac, PILOT_ACS[ ac ] ) is None


@pytest.mark.parametrize( "present,needs,drifts", [
    ( True,  "google.auth",                 False ),  # declared live, IS live        -> ok
    ( True,  "google.cloud.monitoring_v3",  True  ),  # declared live, is ABSENT      -> the bats bug
    ( False, "google.cloud.monitoring_v3",  False ),  # declared absent, IS absent    -> ok
    ( False, "google.auth",                 True  ),  # declared absent, is INSTALLED -> stale register
] )
def test_register_drift_detects_both_directions( present, needs, drifts ):
    """Red-first, committed. The register cannot silently disagree with the host either way."""
    spec = { "needs": needs, "oracle": "x", "instrument_present": present }
    assert ( register_drift( "AC-TEST", spec ) is not None ) is drifts


def test_the_sound_oracle_was_routed_around_the_absent_library_not_left_to_skip():
    """
    🔴 THE FINDING, MADE PERMANENT — and then CLOSED, which is a different claim.

    THE FINDING: §6a rests its entire pilot on Cloud Monitoring being the sound,
    independent oracle. `google.cloud.monitoring_v3` IS NOT INSTALLED on this host. It
    still is not — this test asserts that, so nobody may assume otherwise.

    THE CLOSE: the four ACs riding it were NOT left to rot behind an `importorskip`. They
    were re-pointed at the Monitoring v3 REST surface via google.auth + requests — both
    installed — in cosa/utils/vertex_monitoring_oracle.py. Zero new dependencies, and the
    ACs are written UNCONDITIONALLY, so a missing instrument fails LOUD instead of
    vanishing into a skip.

    The distinction this test exists to defend IS the lesson of the whole cascade:

        "the instrument is missing, so the check SKIPS"     -> a dead check radiating false
                                                               confidence (modules.bats)
        "the instrument is missing, so I ROUTED AROUND it
         and the check RUNS"                                -> an armed check

    A green pilot is now impossible without the sound oracle having actually spoken.
    """
    assert not _available( "google.cloud.monitoring_v3" ), (
        "google-cloud-monitoring is NOW INSTALLED. That is fine — but the REST oracle in "
        "vertex_monitoring_oracle.py is now redundant. Decide DELIBERATELY which one the ACs "
        "ride; never let two oracles for the same fact drift apart."
    )

    monitoring_acs = sorted(
        ac for ac, spec in PILOT_ACS.items()
        if "Monitoring" in spec[ "oracle" ] or "canary" in spec[ "oracle" ]
    )
    assert monitoring_acs == [ "AC-D4", "AC-D4b", "AC-D8", "AC-D9a" ], (
        f"the set of ACs riding the Monitoring oracle changed: {monitoring_acs}. Re-check which "
        f"ACs depend on it before trusting any pilot verdict."
    )

    # ...and every one of them must have a LIVE instrument. If this goes red, an AC the
    # pilot's credibility rests on has been disarmed and would otherwise fail SILENTLY.
    for ac in monitoring_acs:
        assert PILOT_ACS[ ac ][ "instrument_present" ], (
            f"{ac} rides the sound oracle but has NO live instrument — it cannot produce a "
            f"verdict, and must be reported INADMISSIBLE, never as passing."
        )


def test_no_pilot_ac_is_written_against_an_absent_library_behind_a_skip():
    """
    🔴 THE TRAP THIS FILE EXISTS TO SPRING SHUT — and the one I would otherwise have
    walked into myself, an hour after deleting modules.bats for the same sin.

    `pytest.importorskip("google.cloud.monitoring_v3")` is the idiomatic, tidy, utterly
    wrong way to write AC-D4. The library is absent, so the test SKIPS. A skip is
    invisible in a full-suite run. The pilot goes green. The sound oracle was never
    consulted, and the metered-billing cutover ships on an assertion that never ran.

        The tidy idiom and the catastrophic idiom are THE SAME KEYSTROKES.

    So it is banned structurally. When the library lands, write the AC against it
    UNCONDITIONALLY — and let it fail loud if the instrument is missing, which is the
    entire point.
    """
    unit_dir  = os.path.join( PROJECT_ROOT, "src", "tests", "unit" )
    offenders = [
        entry for entry in sorted( os.listdir( unit_dir ) )
        if entry.endswith( ".py" )
        and entry != os.path.basename( __file__ )   # this file NAMES the libs in order to ban them
        and is_dead_check( _read( os.path.join( "src", "tests", "unit", entry ) ) )
    ]
    assert not offenders, (
        "a pilot AC reaches for an ABSENT GCP oracle library behind a skip/ImportError "
        f"guard ({', '.join( ABSENT_ORACLE_LIBRARIES )} are NOT installed). That test does not "
        "run — it SKIPS, invisibly, in a 9,131-test suite, and the pilot goes green on an "
        "assertion that never executed. Write it unconditionally and let it fail loud, or "
        "route the oracle through the installed google.auth + requests REST path. "
        "Offenders: " + ", ".join( offenders )
    )


def _cells( line ):
    """The markdown row's cells, stripped. `| a | b |` -> ['a', 'b']."""
    return [ c.strip() for c in line.strip().strip( "|" ).split( "|" ) ]


def row_subject( line ):
    """
    Which AC does this table row DECLARE? Not "which does it mention" — which is it ABOUT.

    🔴 THIS FUNCTION IS A BUG FIX, AND THE BUG WAS MINE, IN THE FILE THAT LECTURES ABOUT
    THIS EXACT MISTAKE.

    The first version bound a row to the first AC id appearing ANYWHERE in it. But §6a's
    AC table is not the only table in the doc that carries `EXECUTOR:` tags — §6's
    IMPLEMENTATION PLAN does too, and its rows freely MENTION acceptance criteria:

        | **1.4**  | …ONE `rawPredict`… and **IS AC-D8's canary**…        | `EXECUTOR: AI` |
        | **1.0c** | …proof **LAGS** ⇒ **AC-D9b**.                        | `EXECUTOR: AI` |

    So AC-D8's and AC-D9b's EXECUTOR tags were being read off **PHASE ROWS THAT MERELY
    NAME THEM** — 2 of 14 ACs, tags sourced from the wrong table. It passed only because
    both tables happen to say AI. **A guard that is green for the wrong reason is a guard
    that will be green for the wrong reason on the day it matters**, and here is the day:

        Delete the EXECUTOR tag from AC-D8's OWN row and the old parser STILL FOUND ONE
        (from phase 1.4) — so `test_every_ac_carries_an_executor_tag…` stayed GREEN on an
        UNTAGGED AC. And this file's own words are: "an AC with no owner defaults,
        SILENTLY, TO THE HUMAN. That is the exact failure the TEST OWNERSHIP MANDATE
        exists to prevent."

    The false-green ran straight through the assertion built to stop it. So the subject is
    now the id in the row's FIRST CELL — the only cell that DECLARES rather than mentions.
    A phase row ("1.4") has no AC id in cell 0 and is correctly ignored.

    Returns the AC id, or None if this row declares no AC.
    """
    if not line.lstrip().startswith( "|" ):  return None
    cells = _cells( line )
    if not cells:                            return None
    # cell 0 may carry bold/emoji decoration: `**🔴 AC-D0b**`, `**🎯 AC-D4b**`
    found = re.findall( r"\b(AC-D[0-9]+[a-z]?)\b", cells[ 0 ] )
    return found[ 0 ] if found else None


def ac_rows( text ):
    """Every §6a AC-declaring row, keyed by the AC it declares. Duplicates fail loud."""
    rows = {}
    for line in text.splitlines():
        ac = row_subject( line )
        if ac is None:      continue
        if ac in rows:
            raise AssertionError(
                f"{ac} is DECLARED by two different table rows. Two rows for one AC means two "
                f"oracles for one fact, and nobody can say which one the pilot ran."
            )
        rows[ ac ] = line
    return rows


def parse_executor_tags( text ):
    """
    Map every AC id to the EXECUTOR tag on ITS OWN declaring row. Conflicts fail loud.

    Pure over `text` so the CONFLICT branch is exercised by a committed fixture. Left
    inline, that branch would never execute — the doc has no conflicts today — and the
    detection logic would rot unnoticed. Third instance of the same lesson in this file:
    a clean tree never runs your offender path, so the offender path must be tested
    directly or it is not tested at all.
    """
    tags = {}
    for ac, line in ac_rows( text ).items():
        ex = re.search( r"EXECUTOR:\s*\**\s*(AI|HUMAN)", line )
        if ex is None:      continue                 # untagged -> ABSENT, never inherited
        tags[ ac ] = ex.group( 1 )
    return tags


def test_executor_parser_binds_tags_to_the_declaring_row_only():
    """
    🔴 RED-FIRST, COMMITTED — and fixture #3 is the false-green that shipped.

    A phase row that MENTIONS an AC must not supply that AC's tag. Before the fix it did,
    and an AC could lose its own tag while this suite stayed green.
    """
    assert parse_executor_tags( "| **AC-D1** | x | `EXECUTOR: AI` |" )        == { "AC-D1": "AI" }
    assert parse_executor_tags( "| **AC-D0** | x | **`EXECUTOR: HUMAN`** |" ) == { "AC-D0": "HUMAN" }
    # decorated first cell: bold + emoji, exactly as §6a writes AC-D0b / AC-D4b
    assert parse_executor_tags(
        "| **🔴 AC-D0b** | x | `EXECUTOR: AI` |" ) == { "AC-D0b": "AI" }

    # 🔴 THE BUG: a PHASE row that merely mentions AC-D8 supplied AC-D8's tag.
    phase_row = "| **1.4** | the call **IS AC-D8's canary** | `EXECUTOR: AI` |"
    assert parse_executor_tags( phase_row ) == {}, (
        "a phase row that MENTIONS an AC must never DECLARE its executor"
    )

    # …so an AC whose OWN row is untagged now reads as ABSENT (red), not inherited (green).
    untagged = phase_row + "\n| **AC-D8** | zero leakage | | Monitoring canary |"
    assert "AC-D8" not in parse_executor_tags( untagged )

    # a row whose SUBJECT is AC-D8 and which merely mentions AC-D9b binds to its subject
    assert parse_executor_tags( "| **AC-D8** | see AC-D9b | `EXECUTOR: AI` |" ) == { "AC-D8": "AI" }
    # prose (not a table row) is not a tag declaration
    assert parse_executor_tags( "AC-D1 is tagged EXECUTOR: HUMAN in the discussion" ) == {}

    with pytest.raises( AssertionError, match="DECLARED by two different table rows" ):
        ac_rows( "| **AC-D1** | a | `EXECUTOR: AI` |\n| **AC-D1** | b | `EXECUTOR: HUMAN` |" )


def _executor_tags_from_doc():
    return parse_executor_tags( _read( DESIGN_DOC ) )


def test_every_ac_carries_an_executor_tag_and_exactly_one_is_human():
    """
    §D — THE EXECUTOR TAGS, VERIFIED MECHANICALLY.

    The doc's load-bearing claim is: "the set of steps a human must perform is exactly the
    three [phase gates], and NOT ONE OF THEM IS A TEST." Among the ACs that means precisely
    one human executor — AC-D0, an attestation with no machine surface — and thirteen AI.

    Rev. 2 self-certified this in PROSE and got it wrong (F-Rio-R5: it said there was one
    HUMAN gate; there were two). The doc then, rightly, REFUSED to assert a raw grep-count,
    because the literal string `EXECUTOR: HUMAN` also appears in the prose that DISCUSSES
    the gates — "a count that disagrees with a grep is exactly the kind of claim this
    document has been punished for five times."

    So this does not count strings. It MAPS each AC row to its tag and pins the human set.
    That is the assertion the doc wanted and could not safely make about itself — and it
    means the TEST OWNERSHIP MANDATE ("the user is NEVER the tester") is now enforced by a
    test rather than by a promise: the day someone tags an AC `EXECUTOR: HUMAN`, this goes
    red and names it.
    """
    tags = _executor_tags_from_doc()

    missing = sorted( set( PILOT_ACS ) - set( tags ) )
    assert not missing, (
        f"{missing} have NO EXECUTOR tag in the design doc. An untagged AC has no owner — "
        f"and an AC with no owner defaults, silently, to the human. That is the exact failure "
        f"the TEST OWNERSHIP MANDATE exists to prevent."
    )

    human = sorted( ac for ac, ex in tags.items() if ex == "HUMAN" )
    assert human == [ "AC-D0" ], (
        f"the human-executed AC set is {human}, expected exactly ['AC-D0']. Every acceptance "
        f"criterion except the billing attestation MUST be dischargeable by Claude. If a new AC "
        f"is tagged EXECUTOR: HUMAN, it is handing verification back to Rick — who is the "
        f"designer and the user, and NEVER the tester. Replace the oracle; do not tag your way "
        f"out of a bad one."
    )

    # AC-D0 is human ONLY because billing-export config has no API at all (18 Cloud Billing
    # methods, zero export-related). It is an ATTESTATION, not a test handed to a human.
    assert PILOT_ACS[ "AC-D0" ][ "needs" ] is None, (
        "AC-D0 is the one human step and must remain instrument-free — an attestation. If it "
        "ever acquires a machine surface, it stops being Rick's and becomes Claude's."
    )


def test_every_pilot_ac_in_the_design_doc_is_registered():
    """
    THE GUARD THAT GUARDS THE LIST. PILOT_ACS is a COVERAGE list, and coverage lists rot
    by OMISSION — silently (Rio's T1 distinction). §6b's OSQ D-2 went missing from an
    entire revision precisely this way and nobody noticed for two rounds.

    So the register is pinned against the design doc itself: add an AC to §6a without
    registering its instrument here, and this goes red. The list cannot silently fall
    behind the plan it claims to cover.
    """
    # COMMIT-ORDER COUPLING, STATED OUT LOUD RATHER THAN SKIPPED AROUND: this pin reads the
    # design doc. If the doc has not landed yet, that is a REAL red — the register would be
    # pinned to nothing — and it names its own remedy instead of quietly passing.
    assert os.path.exists( os.path.join( PROJECT_ROOT, DESIGN_DOC ) ), (
        f"the §6a design doc is missing at {DESIGN_DOC}, so the AC register is pinned to NOTHING "
        f"and this guard is vacuous. The doc must be committed with (or before) this suite — "
        f"§D's verification cannot outrank the document it verifies. Do NOT skip this test to "
        f"make it pass; land the doc."
    )
    doc = _read( DESIGN_DOC )

    # 🔴 The first pattern here was `\*\*(AC-D[0-9]+[a-z]?)\*\*` — bolded ids only. It
    # MISSED AC-D0b, whose §6a row reads `| **🔴 AC-D0b** |`: the emoji sits INSIDE the
    # bold, so the anchor never matched. (AC-D4b was found only by LUCK, from an unrelated
    # prose mention elsewhere.) A pin that under-reports the doc cannot catch an
    # unregistered AC — it was a guard that could not fail, and the design doc's own §7
    # lesson 4 is "the row that isn't in it." So: match the id ANYWHERE, bold or not. This
    # over-reports rather than under-reports, and over-reporting fails toward MORE
    # registration, which is the safe direction.
    in_doc = set( re.findall( r"\b(AC-D[0-9]+[a-z]?)\b", doc ) )
    assert len( in_doc ) >= 10, (
        f"found only {len( in_doc )} AC ids in the design doc — the pin is near-vacuous and would "
        f"not catch an unregistered AC. Fix the pattern, do not weaken the assertion."
    )

    assert set( PROSE_SHORTHAND ) == { "AC-D9" }, (
        f"the prose-shorthand exclusion set changed: {sorted( PROSE_SHORTHAND )}. This set is the "
        f"ONE way an AC can be absent from the register without failing this test — it must not "
        f"grow silently, or a real AC will hide inside it."
    )

    unregistered = sorted( in_doc - set( PILOT_ACS ) - set( PROSE_SHORTHAND ) )
    assert not unregistered, (
        f"design doc §6a declares {unregistered} but they are NOT in PILOT_ACS. Every AC must "
        f"declare the instrument its oracle needs, or nobody can tell whether it CAN run. "
        f"An unregistered AC is an AC nobody has asked 'does this execute?' about."
    )


# ══════════════════════════════════════════════════════════════════════════════════════
# THE ORACLE SPINE — F-A13 / F-A14 / F-A15, ENFORCED RATHER THAN MERELY FIXED
# ══════════════════════════════════════════════════════════════════════════════════════
#
# Arnold's rev-5 verdict was that the AC table's EXECUTABLE SPINE still encoded the DEAD
# region: phase 1.4 wrote the config at `$LUPIN_GCP_REGION` (= us-central1, where Opus is
# NOT servable); AC-D1 asserted `CLOUD_ML_REGION == $LUPIN_GCP_REGION` — GREEN WHEN THE
# LAUNCHER IS WRONG; AC-D3a's oracle #1 was the publisherModel metadata GET — the LIAR
# that answers 200 for the region that cannot serve and 403 for one that can.
#
# Rev. 6 FIXED all three — in PROSE. And prose is enforced by NOTHING.
#
#     Everything above this line pins WHICH ACs exist and WHO executes them. Not one
#     assertion pins WHAT THEIR ORACLE SAYS. Re-point AC-D1 at $LUPIN_GCP_REGION
#     tomorrow, re-admit the metadata GET to AC-D3a, re-target AC-D4 at us-central1 —
#     and this suite, and all 9,320 tests around it, stay GREEN.
#
# That is Rio's T1 finding one level up ("true today, enforced by nothing tomorrow"), and
# it is the same disease in a third disguise: the fix was applied, and NOTHING WAS ARMED
# TO KEEP IT APPLIED. So the load-bearing clause of every AC's oracle is pinned below.
#
# ⚠️  WHY THESE ARE POSITIVE PINS AND (almost) NEVER BANS. A ban on the dead region is
#     UNSOUND AT ROW GRANULARITY: the rev-6 rows legitimately QUOTE the broken form
#     inside their own warnings ("rev. 5 asserted `== $LUPIN_GCP_REGION`" lives in the
#     AC-D1 row; "Rev. 5 aimed this write at `$LUPIN_GCP_REGION`" lives in phase 1.4).
#     A regex that bans the string goes RED on the corrected doc — a guard that cannot be
#     green on valid text gets neutered by the next person it blocks. So we require what
#     the row MUST say. A regression must DELETE the pinned clause to happen, and then
#     this goes red and names it. The two `never` regexes below are LHS-SCOPED
#     (`CLOUD_ML_REGION == $LUPIN_GCP_REGION`), which the warnings do not match — they are
#     sound precisely because they are narrow.
AC_ORACLE_SPINE = {
    "AC-D0":  { "must": ( "attestation", ),                                    "never": () },
    "AC-D0b": { "must": ( "rawPredict", "NOTHING ELSE MAY WRITE A REGION INTO THE SSOT" ),
                "never": () },
    # F-A14: the AC that certifies the build must not be green on the broken build.
    "AC-D1":  { "must": ( "CLOUD_ML_REGION == $LUPIN_VERTEX_REGION", ),
                "never": ( r"CLOUD_ML_REGION\s*==\s*\$?LUPIN_GCP_REGION", ) },
    "AC-D2":  { "must": ( "red-first", ),                                      "never": () },
    "AC-D3":  { "must": ( "claude -p", ),                                      "never": () },
    # F-A15: the metadata GET is the LIAR. It stays DELETED from the launch guard.
    "AC-D3a": { "must": ( "fetchPublisherModelConfig", "metadata GET is DELETED" ),
                "never": ( r"CLOUD_ML_REGION\s*==\s*\$?LUPIN_GCP_REGION", ) },
    "AC-D4":  { "must": ( "model_invocation_count", "location == $LUPIN_VERTEX_REGION" ),
                "never": ( r"location\s*==\s*\$?LUPIN_GCP_REGION", ) },
    "AC-D4b": { "must": ( "resource label", "LUPIN_VERTEX_REGION" ),           "never": () },
    "AC-D5":  { "must": ( "web-search tool-use block", ),                      "never": () },
    "AC-D6":  { "must": ( "get_session_info", ),                               "never": () },
    "AC-D7":  { "must": ( "COUNT(*)", "schema-agnostic" ),                     "never": () },
    "AC-D8":  { "must": ( "ingestion latency", ),                              "never": () },
    "AC-D9a": { "must": ( "rate card", ),                                      "never": () },
    "AC-D9b": { "must": ( "T+24h", "BigQuery" ),                               "never": () },
}


def spine_violations( row, spec ):
    """Which pinned clauses does this AC row fail? Pure, so both directions get fixtures."""
    bad = [ f"MISSING the pinned clause: {m!r}" for m in spec[ "must" ] if m not in row ]
    bad += [ f"RE-ADMITS the banned form: {n!r}" for n in spec[ "never" ] if re.search( n, row ) ]
    return bad


_SPINE_FIXTURES = [
    # the corrected AC-D1 row: pinned clause present, banned form absent -> clean
    ( "| **AC-D1** | x | `EXECUTOR: AI` | `CLOUD_ML_REGION == $LUPIN_VERTEX_REGION`; ok |",
      "AC-D1", 0 ),
    # the corrected row STILL QUOTES the broken form inside its warning -> must stay clean,
    # or the guard is unusable on the very doc it guards
    ( "| **AC-D1** | x | `EXECUTOR: AI` | `CLOUD_ML_REGION == $LUPIN_VERTEX_REGION` "
      "*(⚠️ rev. 5 asserted `== $LUPIN_GCP_REGION` — a test that passes on the broken "
      "configuration is worse than no test.)* |", "AC-D1", 0 ),
    # 🔴 F-A14 REGRESSION: the clause is re-pointed at the dead region. Both pins bite.
    ( "| **AC-D1** | x | `EXECUTOR: AI` | `CLOUD_ML_REGION == $LUPIN_GCP_REGION` |",
      "AC-D1", 2 ),
    # 🔴 F-A14, quieter: the clause is simply DELETED. The `must` pin still bites.
    ( "| **AC-D1** | x | `EXECUTOR: AI` | pytest over --dry-run; 3 pins |", "AC-D1", 1 ),
    # 🔴 F-A15 REGRESSION: the LIAR is re-admitted by deleting the DELETED sentence.
    ( "| **AC-D3a** | x | `EXECUTOR: AI` | (1) publisherModel metadata GET → 200; "
      "(2) `fetchPublisherModelConfig` → 200 |", "AC-D3a", 1 ),
    # 🔴 F-A13-shaped: AC-D4 re-targeted off the certified variable.
    ( "| **AC-D4** | x | `EXECUTOR: AI` | `model_invocation_count > 0` AND "
      "`location == $LUPIN_GCP_REGION` |", "AC-D4", 2 ),
]


@pytest.mark.parametrize( "row,ac,n_bad", _SPINE_FIXTURES )
def test_spine_pin_bites_on_regression_and_spares_the_corrected_doc( row, ac, n_bad ):
    """
    RED-FIRST, COMMITTED. Fixture 2 is the load-bearing one: the CORRECTED row quotes the
    broken form inside its own warning and MUST still pass. A guard that reds on the fixed
    doc is a guard somebody deletes.
    """
    assert len( spine_violations( row, AC_ORACLE_SPINE[ ac ] ) ) == n_bad


def test_the_spine_pins_cover_every_registered_ac():
    """An AC with no pinned oracle clause is an AC whose oracle may be swapped in silence."""
    assert set( AC_ORACLE_SPINE ) == set( PILOT_ACS ), (
        f"the oracle-spine pin set and the instrument register disagree: "
        f"{sorted( set( AC_ORACLE_SPINE ) ^ set( PILOT_ACS ) )}. Every AC must pin the "
        f"load-bearing clause of its oracle, or that oracle can be re-pointed with nothing "
        f"going red — which is exactly how the dead region survived to rev. 5."
    )


@pytest.mark.parametrize( "ac", sorted( AC_ORACLE_SPINE ) )
def test_every_ac_row_still_pins_its_oracle( ac ):
    """
    🔴 THE SPINE. Each AC's declaring row must still say the thing that makes its oracle
    SOUND. Delete or re-point that clause and this names the AC, the clause, and the file.
    """
    rows = ac_rows( _read( DESIGN_DOC ) )
    assert ac in rows, (
        f"{ac} has NO declaring row in {DESIGN_DOC}. It is registered as a pilot acceptance "
        f"criterion but the design doc no longer declares it."
    )
    bad = spine_violations( rows[ ac ], AC_ORACLE_SPINE[ ac ] )
    assert not bad, (
        f"{ac}'s oracle has been re-pointed in the design doc — {'; '.join( bad )}. This is the "
        f"F-A13/F-A14/F-A15 family: rev. 5 shipped an AC table whose spine asserted "
        f"`CLOUD_ML_REGION == $LUPIN_GCP_REGION` (= us-central1, WHERE THE MODEL CANNOT SERVE), "
        f"so the AC certifying the build was GREEN WHEN THE LAUNCHER WAS WRONG. Rev. 6 fixed the "
        f"prose. THIS is what keeps it fixed."
    )


PLAN_SECTION = ( "## 6. Implementation plan", "### 6a." )


def plan_rows( doc ):
    """
    The table rows of §6 — THE EXECUTABLE SPINE: the instructions a pilot-executing session
    actually follows.

    ⚠️ SCOPED ON PURPOSE, AND THE FIRST DRAFT WAS NOT. It grepped the WHOLE doc for
    `setPublisherModelConfig` and went red on two rows that instruct nobody: a §4a
    GLOSSARY row (defining what the config's `location` field means) and a CHANGELOG row
    (recording that OSQ R-2 asks whether the API even accepts `location=global`). Both are
    PROSE ABOUT the write. Only §6 IS the write.

    A guard that reds on the corrected document gets deleted by the next person it blocks —
    so it must fire on the instruction and nothing else.
    """
    start = doc.index( PLAN_SECTION[ 0 ] )
    end   = doc.index( PLAN_SECTION[ 1 ], start )
    return [ l for l in doc[ start:end ].splitlines() if l.lstrip().startswith( "|" ) ]


def test_phase_1_4_writes_the_config_at_the_certified_region_variable():
    """
    🔴 F-A13 — the single most important WRITE in the plan, and it is executed by a SESSION
    READING THIS ROW. No amount of correctness in vertex_env.py can protect it: the
    `setPublisherModelConfig` call is made by the pilot-executing session following the
    plan, not by the launcher. Rev. 5 pointed it at `$LUPIN_GCP_REGION` = `us-central1` —
    the documented catastrophe — and only prose ever moved it back.
    """
    rows = plan_rows( _read( DESIGN_DOC ) )
    assert len( rows ) >= 5, (
        f"the §6 implementation-plan table has collapsed to {len( rows )} rows — this pin is "
        f"near-vacuous. Fix the section markers {PLAN_SECTION}; do not weaken the assertion."
    )

    writes = [ l for l in rows if "setPublisherModelConfig" in l ]
    assert writes, (
        "NO row in the §6 implementation plan writes the publisher-model config any more. If "
        "phase 1.4 was renamed or moved, RE-POINT THIS PIN AT THE ROW THAT MAKES THE WRITE — do "
        "not delete the pin, or the single most dangerous write in the plan goes unguarded."
    )
    for row in writes:
        assert "$LUPIN_VERTEX_REGION" in row, (
            "the setPublisherModelConfig write does NOT name `$LUPIN_VERTEX_REGION` as its "
            "target region. The ONLY certified Vertex region variable is LUPIN_VERTEX_REGION "
            "(= global). LUPIN_GCP_REGION is the CONTAINER-DEPLOY region (us-central1), where "
            "claude-opus-4-8 is NOT SERVABLE — rawPredict returns 400. Rev. 5 aimed this exact "
            "write there, and it is the write that would have burned metered Opus in a region "
            "that cannot serve it."
        )


def test_the_docs_certified_region_equals_the_code_ssot():
    """
    🔴 THE DOC↔CODE CROSS-PIN — the one assertion that makes the region a single fact.

    The doc declares the certified value inline ("`$LUPIN_VERTEX_REGION` (= `global`)").
    The code declares it in `vertex_env.CERTIFIED_VERTEX_REGIONS`. Two declarations of one
    fact WILL drift — that is what §7 is a monument to. So they are pinned to each other:
    certify a region in code and the doc must say so, and vice versa.
    """
    doc      = _read( DESIGN_DOC )
    declared = re.findall( r"LUPIN_VERTEX_REGION`?\**[^\n]{0,24}?\(=\s*\**`([a-z0-9-]+)`", doc )

    assert len( declared ) >= 3, (
        f"only {len( declared )} inline region declarations found in the doc — this pin is "
        f"near-vacuous and would not catch a drift. Fix the pattern; do not weaken the assertion."
    )
    assert set( declared ) == set( CERTIFIED_VERTEX_REGIONS ), (
        f"the design doc declares LUPIN_VERTEX_REGION = {sorted( set( declared ) )}, but the code "
        f"SSOT (vertex_env.CERTIFIED_VERTEX_REGIONS) certifies {sorted( CERTIFIED_VERTEX_REGIONS )}. "
        f"ONE of them is wrong and the pilot will believe whichever it reads first. Only a "
        f"`rawPredict` -> 200 may certify a region (AC-D0b) — not metadata, not a quota row."
    )
    assert "us-central1" not in declared, (
        "the doc declares us-central1 as the Vertex region. rawPredict -> 400 there: THE MODEL "
        "CANNOT SERVE. This is the exact write three revisions of this design got wrong."
    )


def test_the_ac_d8_negative_is_a_canary_never_a_clock():
    """
    ⚠️ AC-D8 asserts a NEGATIVE against a LAGGING oracle — the most dangerous assertion in
    the document. Cloud Monitoring's descriptor declares `ingestDelay: None`, so ANY
    hardcoded wait is an assumption wearing a constant's clothing: Google changes the real
    delay and every negative test starts passing FOR THE WRONG REASON, silently, forever.

    The protocol must therefore stay a CANARY (poll until a KNOWN call appears, then and
    only then trust the silence) and never a CLOCK. Pinned so it cannot decay back into a
    sleep — which is the cheapest, most tempting edit anyone will ever make to this AC.
    """
    doc = _read( DESIGN_DOC )
    for clause in ( "FIRE THE CANARY", "NEVER a fixed sleep", "INADMISSIBLE" ):
        assert clause in doc, (
            f"AC-D8's canary protocol has lost {clause!r}. If the canary has been replaced by a "
            f"fixed wait, the negative assertion PASSES BECAUSE THE DATA HAS NOT LANDED YET — "
            f"absence of output read as absence of the event, which is this cascade's founding "
            f"bug, re-committed inside the AC written to replace a bad oracle."
        )


# The ONE AC allowed to carry a `TBD` in its oracle cell — and it is tolerated only
# because it ALSO names two mechanisms that are NOT TBD. The set is PINNED (Rio's T1): a
# hollow tag must never be able to join it in silence.
TBD_TOLERATED = {
    "AC-D6": "OSQ-3 (the STRONGER assertion — 'an MCP tool resolved in a headless run') is "
             "genuinely unnamed, and the doc refuses to fake a mechanism. But the AC is NOT "
             "hollow: it names `get_session_info()` round-trip + tool-list presence, both of "
             "which execute. The TBD is an ambition, not the oracle.",
}


def test_no_ai_tagged_ac_hands_a_hollow_mechanism_back():
    """
    🔴 THE MANAGER'S STANDING RULE: **NO AC MAY HAND WORK BACK TO RICK.** A bare
    `EXECUTOR: AI` whose mechanism is a TBD is HOLLOW — it LOOKS discharged by Claude and
    is in fact discharged by nobody, which in practice means it lands on the human at the
    exact moment everyone is celebrating a green pilot.

    The HUMAN-tag count is pinned elsewhere. This pins the subtler failure: the tag says AI
    and the oracle says *nothing*.
    """
    rows = ac_rows( _read( DESIGN_DOC ) )
    tags = parse_executor_tags( _read( DESIGN_DOC ) )

    assert set( TBD_TOLERATED ) == { "AC-D6" }, (
        f"the TBD-tolerance set changed: {sorted( TBD_TOLERATED )}. This is the ONE way an AI-tagged "
        f"AC may carry an unnamed mechanism. It must not grow silently — that is how a hollow tag "
        f"gets a home."
    )

    hollow = []
    for ac, executor in tags.items():
        if executor != "AI":                    continue
        oracle = _cells( rows[ ac ] )[ -1 ]
        if "TBD" in oracle and ac not in TBD_TOLERATED:
            hollow.append( ac )
    assert not hollow, (
        f"{hollow} are tagged `EXECUTOR: AI` but their oracle is a TBD. That tag is HOLLOW: it "
        f"claims Claude discharges the AC while naming no mechanism that could. Name a real "
        f"oracle or mark the AC INADMISSIBLE — do not tag your way out of a bad oracle."
    )

    # …and the one tolerated TBD must STILL name a mechanism that actually executes.
    assert "get_session_info" in rows[ "AC-D6" ], (
        "AC-D6's tolerated TBD (OSQ-3) is only tolerable because the row ALSO names the "
        "`get_session_info()` round-trip — a mechanism that runs. That clause is gone, so the "
        "TBD is now the whole oracle and the tag is hollow."
    )
