"""
AC-D1 / AC-D2 — Vertex toggle env composition and guards.

Design: src/rnd/v0.1.9/2026.07.13-vertex-model-garden-toggle-search-and-logging.md

AC-D2 is RED-FIRST BY CONSTRUCTION: every guard is proven to FAIL on the hostile
input before the happy path is asserted. A guard with no red-first test is an
unproven guard, and an unproven guard is decoration.

These tests pass an explicit `env` mapping rather than mutating os.environ, so a
stray variable in the developer's shell can never turn a guard test green.
"""

import pathlib

import pytest

import cosa.utils.vertex_env as vertex_env

from cosa.utils.vertex_env import (
    ADMISSIBLE_REGION_ORACLES,
    SERVER_TAINT_REFUSAL_KEYS,
    assert_server_env_is_vertex_free,
    pane_guard,
    parse_tmux_global_env,
    ASSERTABLE_MODEL_OVERRIDES,
    ASSERTABLE_PROJECT_OVERRIDES,
    CERTIFIED_VERTEX_REGIONS,
    HOSTILE_ENV_KEYS,
    MAX_PANE_UNSET_KEYS,
    PANE_UNSET_KEYS,
    pane_unset_keys,
    REGION_BLIND_EVIDENCE_FRAGMENTS,
    VERTEX_REGION_CERTIFICATIONS,
    VERTEX_SESSION_KEYS,
    MODEL_PINS,
    PER_MODEL_REGION_OVERRIDES,
    VERTEX_REGION_ENV_KEY,
    VertexEnvError,
    assert_certifications_are_provenanced,
    quick_smoke_test,
    assert_no_hostile_env,
    assert_project_agreement,
    assert_region_oracle_is_admissible,
    compose_vertex_env,
    format_dry_run,
)


CLEAN_ENV = { "LUPIN_GCP_PROJECT_ID": "proj-x", VERTEX_REGION_ENV_KEY: "global" }


# ---------------------------------------------------------------------------
# AC-D2 — RED FIRST. Every guard is shown to FAIL before anything is green.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize( "hostile_key", HOSTILE_ENV_KEYS )
def test_every_hostile_key_refuses_to_launch( hostile_key ):
    """
    Each hostile variable must abort. Parametrized over the WHOLE set, so adding a
    key to HOSTILE_ENV_KEYS without a guard becomes impossible.
    """
    with pytest.raises( VertexEnvError ) as exc:
        compose_vertex_env( env={ **CLEAN_ENV, hostile_key: "anything" } )
    assert hostile_key in str( exc.value )


def test_per_model_region_override_is_the_region_trap_in_disguise():
    """
    One inherited VERTEX_REGION_CLAUDE_4_8_OPUS routes OPUS ALONE to another region
    — where it runs, bills, and logs nothing, while every other model behaves.
    """
    with pytest.raises( VertexEnvError ):
        compose_vertex_env( env={ **CLEAN_ENV, "VERTEX_REGION_CLAUDE_4_8_OPUS": "us-east5" } )


def test_google_application_credentials_defeats_the_project_guard():
    """
    A different service-account key means a DIFFERENT PROJECT — the hole straight
    through the guard this design once called "the highest-value guard in the script".
    """
    with pytest.raises( VertexEnvError ):
        compose_vertex_env( env={ **CLEAN_ENV, "GOOGLE_APPLICATION_CREDENTIALS": "/tmp/other.json" } )


def test_a_disagreeing_anthropic_model_defeats_the_pins():
    """A pin you can override from the environment is a preference, not a pin."""
    with pytest.raises( VertexEnvError ):
        compose_vertex_env( env={ **CLEAN_ENV, "ANTHROPIC_MODEL": "claude-3-haiku" } )


def test_project_disagreement_refuses_to_launch():
    """GOOGLE_CLOUD_PROJECT takes PRECEDENCE — a mismatch bills another project, silently."""
    with pytest.raises( VertexEnvError ) as exc:
        compose_vertex_env( env={ **CLEAN_ENV, "GOOGLE_CLOUD_PROJECT": "someone-elses-project" } )
    assert "PRECEDENCE" in str( exc.value )


def test_project_agreement_passes_when_values_match():
    """A guard that always fires is as useless as one that never does."""
    composed = compose_vertex_env( env={ **CLEAN_ENV, "GOOGLE_CLOUD_PROJECT": "proj-x" } )
    assert composed[ "ANTHROPIC_VERTEX_PROJECT_ID" ] == "proj-x"


def test_missing_project_refuses_to_launch():
    with pytest.raises( VertexEnvError ) as exc:
        compose_vertex_env( env={ VERTEX_REGION_ENV_KEY: "global" } )
    assert "LUPIN_GCP_PROJECT_ID" in str( exc.value )


def test_missing_region_refuses_to_launch():
    """There is no safe default region: us-central1 CANNOT SERVE the model."""
    with pytest.raises( VertexEnvError ) as exc:
        compose_vertex_env( env={ "LUPIN_GCP_PROJECT_ID": "proj-x" } )
    assert VERTEX_REGION_ENV_KEY in str( exc.value )


def test_empty_string_is_treated_as_missing():
    """An empty value is absence wearing a value's clothing."""
    with pytest.raises( VertexEnvError ):
        compose_vertex_env( env={ **CLEAN_ENV, VERTEX_REGION_ENV_KEY: "" } )


def test_all_offenders_are_named_not_just_the_first():
    """A caller who fixes one and re-runs must not discover the next one serially."""
    hostile = { "ANTHROPIC_VERTEX_BASE_URL": "x", "GOOGLE_APPLICATION_CREDENTIALS": "y" }
    with pytest.raises( VertexEnvError ) as exc:
        compose_vertex_env( env={ **CLEAN_ENV, **hostile } )
    message = str( exc.value )
    assert "ANTHROPIC_VERTEX_BASE_URL" in message and "GOOGLE_APPLICATION_CREDENTIALS" in message


# ---------------------------------------------------------------------------
# AC-D1 — env composition is exactly right
# ---------------------------------------------------------------------------

def test_composition_is_exact():
    composed = compose_vertex_env( env=CLEAN_ENV )
    assert composed == {
        "CLAUDE_CODE_USE_VERTEX"         : "1",
        "CLOUD_ML_REGION"                : "global",
        "ANTHROPIC_VERTEX_PROJECT_ID"    : "proj-x",
        "ANTHROPIC_DEFAULT_OPUS_MODEL"   : "claude-opus-4-8",
        "ANTHROPIC_DEFAULT_SONNET_MODEL" : "claude-sonnet-4-6",
        "ANTHROPIC_DEFAULT_HAIKU_MODEL"  : "claude-haiku-4-5@20251001",
    }


def test_region_comes_from_the_vertex_key_not_the_container_deploy_key():
    """
    F-A12: LUPIN_GCP_REGION is the CONTAINER-DEPLOY region (us-central1) — where
    claude-opus-4-8 is NOT SERVABLE. A shared name is not sameness.
    """
    env = { **CLEAN_ENV, "LUPIN_GCP_REGION": "us-central1" }
    composed = compose_vertex_env( env=env )
    assert composed[ "CLOUD_ML_REGION" ] == "global"
    assert composed[ "CLOUD_ML_REGION" ] != env[ "LUPIN_GCP_REGION" ]


def test_haiku_pin_uses_the_at_form_not_the_hyphenated_form():
    """Dated snapshots use '@' on Vertex; the hyphenated form resolves elsewhere."""
    assert MODEL_PINS[ "ANTHROPIC_DEFAULT_HAIKU_MODEL" ] == "claude-haiku-4-5@20251001"
    assert "-20251001" not in MODEL_PINS[ "ANTHROPIC_DEFAULT_HAIKU_MODEL" ]


def test_explicit_arguments_override_the_environment():
    composed = compose_vertex_env( env=CLEAN_ENV, project_id="other-proj", region="global" )
    assert composed[ "ANTHROPIC_VERTEX_PROJECT_ID" ] == "other-proj"
    assert composed[ "CLOUD_ML_REGION" ]             == "global"


def test_an_explicit_region_argument_is_certified_too():
    """
    The region allowlist must not be bypassable by passing region= directly. A guard
    you can route around by choosing a different call signature is not a guard.
    """
    with pytest.raises( VertexEnvError ):
        compose_vertex_env( env=CLEAN_ENV, region="us-central1" )


def test_all_fifteen_per_model_overrides_are_guarded():
    """The binary ships 15. Guarding 14 would leave exactly one silent hole."""
    assert len( PER_MODEL_REGION_OVERRIDES ) == 15
    assert "VERTEX_REGION_CLAUDE_4_8_OPUS" in PER_MODEL_REGION_OVERRIDES


def test_dry_run_renders_sorted_key_value_lines():
    rendered = format_dry_run( compose_vertex_env( env=CLEAN_ENV ) )
    lines = rendered.splitlines()
    assert lines == sorted( lines )
    assert "CLOUD_ML_REGION=global" in lines


def test_assert_helpers_pass_on_clean_input():
    """Cover the no-op branch of each guard — a guard must also be able to NOT fire."""
    assert assert_no_hostile_env( CLEAN_ENV ) is None
    assert assert_project_agreement( CLEAN_ENV, "proj-x" ) is None


def test_defaults_to_the_real_process_environment( monkeypatch ):
    """
    The `env=None` default path — the ONE branch every other test bypasses by passing
    an explicit mapping. Left uncovered, the production call site (which passes nothing)
    would be the only untested path in the module.

    Fitting, given the day's lesson: a default is a null wearing a confident face.
    """
    monkeypatch.setenv( "LUPIN_GCP_PROJECT_ID", "proj-from-os-environ" )
    monkeypatch.setenv( VERTEX_REGION_ENV_KEY, "global" )
    for hostile_key in HOSTILE_ENV_KEYS:
        monkeypatch.delenv( hostile_key, raising=False )
    for project_key in ( "GOOGLE_CLOUD_PROJECT", "GCLOUD_PROJECT" ):
        monkeypatch.delenv( project_key, raising=False )

    composed = compose_vertex_env()
    assert composed[ "ANTHROPIC_VERTEX_PROJECT_ID" ] == "proj-from-os-environ"
    assert composed[ "CLOUD_ML_REGION" ]             == "global"


def test_the_real_environment_is_guarded_too( monkeypatch ):
    """The guards must fire on os.environ, not only on an injected mapping."""
    monkeypatch.setenv( "LUPIN_GCP_PROJECT_ID", "proj-x" )
    monkeypatch.setenv( VERTEX_REGION_ENV_KEY, "global" )
    monkeypatch.setenv( "VERTEX_REGION_CLAUDE_4_8_OPUS", "us-east5" )

    with pytest.raises( VertexEnvError ):
        compose_vertex_env()


# ---------------------------------------------------------------------------
# C2 — the region allowlist the word "enforce" was standing in for
# ---------------------------------------------------------------------------

def test_uncertified_region_refuses_to_launch():
    """
    The module ACCEPTED any string and exited 0 — including `us-central1`, the DEAD
    region where claude-opus-4-8 is NOT SERVABLE. The docstring claimed it "enforces
    a constant certified once". It enforced nothing.
    """
    with pytest.raises( VertexEnvError ) as exc:
        compose_vertex_env( env={ **CLEAN_ENV, VERTEX_REGION_ENV_KEY: "us-central1" } )
    assert "not a CERTIFIED Vertex region" in str( exc.value )


def test_the_dead_region_is_not_certified():
    """us-central1 is where three revisions of this design pointed. rawPredict -> 400."""
    assert "us-central1" not in CERTIFIED_VERTEX_REGIONS
    assert "global" in CERTIFIED_VERTEX_REGIONS


def test_quota_starved_region_is_not_certified():
    """
    us-east5 SERVES (429, quota-starved) — so it is not "dead". It is still not
    certified: a region that 429s under any real load is not a region you launch on.
    Servable is not the same as usable.
    """
    assert "us-east5" not in CERTIFIED_VERTEX_REGIONS


def test_certified_region_passes():
    """Positive control: without it, every refusal above is unattributable."""
    assert compose_vertex_env( env=CLEAN_ENV )[ "CLOUD_ML_REGION" ] == "global"


# ---------------------------------------------------------------------------
# C4 — model overrides are ASSERTABLE, not bannable
# ---------------------------------------------------------------------------

def test_agreeing_model_override_is_harmless():
    """
    ANTHROPIC_MODEL=claude-opus-4-8 is EXACTLY what the pin asks for. Aborting on it
    is the "guard that fires on a valid configuration" bug — fixed once for the
    project vars, and not swept into the sibling category.
    """
    composed = compose_vertex_env( env={ **CLEAN_ENV, "ANTHROPIC_MODEL": "claude-opus-4-8" } )
    assert composed[ "ANTHROPIC_DEFAULT_OPUS_MODEL" ] == "claude-opus-4-8"


def test_disagreeing_model_override_refuses_to_launch():
    """It OVERRIDES the pin — so a disagreement silently runs a model nobody priced."""
    with pytest.raises( VertexEnvError ) as exc:
        compose_vertex_env( env={ **CLEAN_ENV, "ANTHROPIC_MODEL": "claude-3-haiku" } )
    assert "DISAGREES" in str( exc.value )


def test_agreeing_small_fast_model_is_harmless():
    composed = compose_vertex_env(
        env={ **CLEAN_ENV, "ANTHROPIC_SMALL_FAST_MODEL": "claude-haiku-4-5@20251001" }
    )
    assert composed[ "ANTHROPIC_DEFAULT_HAIKU_MODEL" ] == "claude-haiku-4-5@20251001"


def test_disagreeing_small_fast_model_refuses_to_launch():
    with pytest.raises( VertexEnvError ):
        compose_vertex_env( env={ **CLEAN_ENV, "ANTHROPIC_SMALL_FAST_MODEL": "claude-3-haiku" } )


# ---------------------------------------------------------------------------
# C1 — the pane scrub must be WIDER than the launcher guard set
# ---------------------------------------------------------------------------

def test_pane_unset_covers_the_project_precedence_stealers():
    """
    THE WRONG-PROJECT HOLE. The launcher can ASSERT the project vars; the PANE cannot —
    it inherits the FROZEN tmux server env, whose values the launcher never saw. A stale
    GOOGLE_CLOUD_PROJECT there TAKES PRECEDENCE and bills the wrong project, silently,
    with every launcher-side guard green.
    """
    for key in ( "GOOGLE_CLOUD_PROJECT", "GCLOUD_PROJECT", "GOOGLE_APPLICATION_CREDENTIALS" ):
        assert key in PANE_UNSET_KEYS, f"{key} can bill the wrong project from the pane"


def test_pane_unset_is_strictly_wider_than_the_launcher_hostile_set():
    """The pane cannot assert, so it must scrub what the launcher merely compares."""
    assert set( HOSTILE_ENV_KEYS ) < set( PANE_UNSET_KEYS )
    for key in ASSERTABLE_PROJECT_OVERRIDES:
        assert key in PANE_UNSET_KEYS
    for key in ASSERTABLE_MODEL_OVERRIDES:
        assert key in PANE_UNSET_KEYS


# ---------------------------------------------------------------------------
# OSQ-6 — the MAX-path leak. The inverse hole, and the worse one.
# ---------------------------------------------------------------------------

def test_the_vertex_path_never_scrubs_what_it_just_forwarded():
    """
    🔴 THE P0. THIS IS THE TEST THAT WOULD HAVE CAUGHT IT, AND IT DID NOT EXIST.

    The launcher forwarded the three toggle keys into the pane via `tmux -e` and then
    made the pane's FIRST ACT `unset` them. `--vertex` printed a METERED-BILLING banner
    and ran on MAX. C1 (scrub the pane) and OSQ-6 (scrub every path) are each correct
    ALONE; the defect lived in their COMPOSITION with the -e forward — the seam, which
    is precisely where nobody looked, because both halves were already done and green.

    WHY THE OLD SUITE NOTARIZED THE LIE INSTEAD OF CATCHING IT: the receipt was "the
    pane sees <unset>" — which is EQUALLY TRUE when the hole is closed and when the
    FEATURE IS DEAD. That green COULD NOT HAVE COME OUT OTHERWISE, so it was never
    evidence. The old test asserted `key in VERTEX_SESSION_KEYS`: a tautology over a
    literal, restating the constant back to itself. It could not fail.

    So this one is DERIVED from the two sets that actually have to disagree, and it CAN
    fail: whatever compose EMITS, the vertex pane must NOT scrub. Reintroduce the bug and
    the intersection is non-empty and this goes red, naming the exact keys it deleted.
    """
    forwarded = set( compose_vertex_env( env=CLEAN_ENV ) )
    scrubbed  = set( pane_unset_keys( vertex_path=True ) )

    assert forwarded & scrubbed == set(), (
        f"THE SCRUB IS EATING THE FEATURE: --vertex forwards {sorted( forwarded & scrubbed )} "
        "via `tmux -e` and then the pane unsets them. The session runs on MAX while the "
        "banner says VERTEX. It fails safe, but the banner LIES — and the banner is what "
        "a human trusts."
    )


def test_the_vertex_path_preserves_all_three_toggle_keys():
    """Said positively, because a disjointness assertion also passes if compose emits nothing."""
    scrubbed = set( pane_unset_keys( vertex_path=True ) )
    for key in VERTEX_SESSION_KEYS:
        assert key not in scrubbed, f"--vertex would delete {key} — the toggle cannot survive that"


def test_the_max_path_scrubs_every_toggle_key():
    """
    OSQ-6, and it must SURVIVE the P0 fix — this is the half that must NOT regress while
    fixing the other half. A tmux server born from a Vertex shell freezes
    CLAUDE_CODE_USE_VERTEX into its env and hands it to EVERY later session on that
    socket, MAX ONES INCLUDED (verified live). That session never asked to be billed.
    """
    scrubbed = set( pane_unset_keys( vertex_path=False ) )
    for key in VERTEX_SESSION_KEYS:
        assert key in scrubbed, f"{key} could silently put a Max session on metered billing"


def test_the_vertex_path_still_scrubs_everything_hostile():
    """
    The fix must narrow the scrub by EXACTLY the toggle keys and not one key more. C1 (the
    wrong-project hole) and the per-model region overrides must still die on BOTH paths —
    a fix that reopens the hole it was patched around is not a fix.
    """
    scrubbed = set( pane_unset_keys( vertex_path=True ) )
    for key in HOSTILE_ENV_KEYS + ASSERTABLE_PROJECT_OVERRIDES:
        assert key in scrubbed, f"{key} still bills the wrong project / region from the pane"


def test_max_scrub_is_the_vertex_scrub_plus_exactly_what_the_vertex_path_forwards():
    """
    The two paths differ by EXACTLY THE SET --vertex FORWARDS, and nothing else.

    🔴 THIS TEST WENT RED WHEN C5 WAS FIXED, AND THAT IS THE POINT. It used to assert the
    difference was `VERTEX_SESSION_KEYS` — the three toggle keys — which quietly encoded the
    very incompleteness C5 closed: it said the MAX path need only scrub the toggle keys, when
    the true rule is that the MAX path must scrub EVERYTHING the vertex path forwards, model
    pins included. A restated subset, asserted as if it were the whole rule.

    So it is now derived from compose itself: widen what --vertex emits and this difference
    widens with it, automatically. No literal to fall behind its source.
    """
    vertex_scrub = set( pane_unset_keys( vertex_path=True ) )
    max_scrub    = set( pane_unset_keys( vertex_path=False ) )

    assert max_scrub - vertex_scrub == set( compose_vertex_env( env=CLEAN_ENV ) )
    assert set( VERTEX_SESSION_KEYS ) < ( max_scrub - vertex_scrub )
    assert vertex_scrub < max_scrub


def test_the_model_pins_survive_the_vertex_pane():
    """
    The pins ride the same -e forward as the toggle keys, so the same seam could eat them.
    It didn't — ANTHROPIC_DEFAULT_* are not in the scrub set while ANTHROPIC_MODEL is —
    but that is a fact worth an assertion rather than a lucky spacing of two tuples.
    """
    scrubbed = set( pane_unset_keys( vertex_path=True ) )
    for pin in MODEL_PINS:
        assert pin not in scrubbed, f"{pin} would be deleted — the session runs an unpinned model"


def test_the_launcher_derives_the_key_lists_and_never_restates_them():
    """
    FLAG D. The launcher used to hardcode ( "CLAUDE_CODE_USE_VERTEX", "CLOUD_ML_REGION",
    "ANTHROPIC_VERTEX_PROJECT_ID" ) as a literal — two lines below an import of the module
    that already defined them. That is the drift class this whole design guards: the literal
    silently falls behind its source, and the unit suite stays green because it tests the
    SOURCE, not the RESTATEMENT.

    Shipping a guard that carries the wart it guards against is the worst of both. So: grep
    the shell for the toggle keys appearing as bare string literals. They must be IMPORTED.

    (This reads the real script — the same reason test_vertex_env_completeness.py scrapes the
    real binary. A rule tested against a fixture of itself is a rule tested against nothing.)
    """
    launcher = pathlib.Path( __file__ ).resolve().parents[ 2 ] / "scripts" / "start-cc-with-tmux.sh"
    source   = launcher.read_text()

    # Strip comments: the keys are NAMED in the doctrine blocks on purpose, and that prose
    # is the point — it is the executable lines that must not restate them.
    code = "\n".join(
        line for line in source.splitlines() if not line.lstrip().startswith( "#" )
    )

    for key in VERTEX_SESSION_KEYS:
        assert f'"{key}"' not in code, (
            f"{launcher.name} restates {key} as a string literal instead of importing "
            "VERTEX_SESSION_KEYS / MAX_PANE_UNSET_KEYS. DERIVE, DON'T RESTATE — a restated "
            "list falls behind its source in silence."
        )


def test_every_key_compose_emits_is_scrubbed_on_the_max_path():
    """
    🔴 C5 (Rio, 2026-07-14). THE TEST THAT USED TO LIVE HERE SUBTRACTED THE ANSWER BEFORE
    ASKING THE QUESTION:

        emitted = set( compose_vertex_env( env=CLEAN_ENV ) ) - set( MODEL_PINS )   # <-- !!
        assert emitted == set( VERTEX_SESSION_KEYS )

    Its docstring read "a key we EMIT but never SCRUB is a key a tainted server can forge"
    — and then it removed, BY NAME, the only keys for which that was true. A test weakened
    until it passed, wearing the docstring of the test that would have caught the bug. It
    could not fail, and it sat inside the fix for the last guard that could not fail.

    THE HONEST INVARIANT: every key --vertex forwards via `-e` is a key a frozen tmux server
    can hand a MAX pane FOR FREE. So the MAX scrub must cover ALL of them — the model pins
    included, where a forgery is not a mis-billing but a SILENT MODEL SUBSTITUTION.
    """
    emitted  = set( compose_vertex_env( env=CLEAN_ENV ) )
    scrubbed = set( pane_unset_keys( vertex_path=False ) )

    forgeable = emitted - scrubbed
    assert not forgeable, (
        f"compose EMITS {sorted( forgeable )} and the MAX pane does NOT scrub them. A tmux "
        "server frozen from a Vertex shell hands those keys to a MAX session that never asked "
        "for them — and for a model pin that is not a mis-billing, it is a SILENT MODEL "
        "SUBSTITUTION, with every other guard green."
    )


def test_the_max_scrub_is_the_vertex_scrub_plus_everything_compose_forwards():
    """
    Said the other way, so the two cannot drift apart: the MAX path scrubs exactly what the
    VERTEX path scrubs, PLUS everything the vertex path forwards. Derived from the sets that
    have to disagree — never restated as a literal.
    """
    assert set( pane_unset_keys( vertex_path=False ) ) == (
        set( pane_unset_keys( vertex_path=True ) ) | set( compose_vertex_env( env=CLEAN_ENV ) )
    )


def test_the_model_pins_are_still_forwarded_intact_on_the_vertex_path():
    """
    POSITIVE CONTROL for the fix above. Adding the pins to the MAX scrub must NOT leak into
    the VERTEX scrub — that would be the P0 all over again (scrubbing what we just forwarded),
    and its failure mode is the one that lies: a --vertex session silently running an OLDER
    Opus because its own launcher deleted the pin.
    """
    scrubbed = set( pane_unset_keys( vertex_path=True ) )
    for pin in MODEL_PINS:
        assert pin not in scrubbed, f"--vertex would delete {pin} — the pin cannot survive that"


# ---------------------------------------------------------------------------
# 13c3c480 — THE REGION-BLIND ORACLE. The MaaS OpenAI-compat endpoint returns a
# BYTE-IDENTICAL 200 for a live region, the dead region, and a region that does not
# exist — while its 404 body claims to check "the specified region".
#
# The trap is not that we used it. We did not; CERTIFIED_VERTEX_REGIONS was built
# from rawPredict, which genuinely 400s on us-central1. The trap is that a FUTURE
# seat would reach for it, get a 200, and widen the allowlist to a region where the
# model cannot run — pilot green, money spent, nothing logged.
#
# So the guard sits on the ACT OF WIDENING THE ALLOWLIST, which is the only surface
# that mistake has to cross. A PROOF IS NOT A GUARD.
# ---------------------------------------------------------------------------

# The exact evidence a future seat would paste in, having run the probe that lied.
OPENAI_COMPAT_EVIDENCE = (
    "POST .../locations/us-central1/endpoints/openapi/chat/completions -> 200, content 'OK'"
)


def test_the_openai_compat_endpoint_cannot_certify_a_region():
    """
    THE FINDING, AS A GUARD. deepseek-v3.2-maas returned 200 / 1418 bytes / "OK" from
    `global`, from the DEAD `us-central1`, and from the FICTIONAL `narnia-1` — byte
    for byte. The MODEL axis discriminates (a bogus model 404s); the REGION axis is
    BLIND. An observation is evidence only if it could have come out otherwise.
    """
    with pytest.raises( VertexEnvError ) as exc:
        assert_certifications_are_provenanced( {
            "us-central1" : { "oracle": "openai-compat", "evidence": OPENAI_COMPAT_EVIDENCE }
        } )
    message = str( exc.value )
    assert "us-central1" in message
    assert "not an admissible region oracle" in message


def test_the_lie_is_caught_even_when_the_oracle_field_says_rawpredict():
    """
    BELT AND SUSPENDERS, aimed at the honest-but-sloppy seat rather than the liar: a
    record that CLAIMS rawPredict while pasting OpenAI-compat evidence is refused on
    the evidence, not on the label. The oracle field is a claim; the evidence is the
    only part of the record that can contradict it.
    """
    with pytest.raises( VertexEnvError ) as exc:
        assert_region_oracle_is_admissible( "rawPredict", OPENAI_COMPAT_EVIDENCE + " rawPredict" )
    assert "endpoints/openapi" in str( exc.value )


@pytest.mark.parametrize( "fragment", REGION_BLIND_EVIDENCE_FRAGMENTS )
def test_every_region_blind_fragment_is_refused( fragment ):
    """Parametrized over the whole set — a fragment listed but unguarded is impossible."""
    with pytest.raises( VertexEnvError ):
        assert_region_oracle_is_admissible( "rawPredict", f"rawPredict via {fragment} -> 200" )


def test_the_region_blind_fragment_set_is_not_vacuous():
    """
    Caught by the red-first run itself, and it is the day's lesson wearing a new face:
    emptying REGION_BLIND_EVIDENCE_FRAGMENTS turns the parametrized test ABOVE into a
    SKIP — pytest reports "1 skipped", the suite stays green, and the fragment guard is
    silently retired by the very act of deleting what it guards.

    A parametrized test over an empty set is a test that has never been red. "I could
    not check" must never be reported as "I checked."
    """
    assert REGION_BLIND_EVIDENCE_FRAGMENTS, (
        "emptying this tuple retires the fragment guard AND downgrades its test to a skip"
    )


def test_a_region_cannot_be_certified_anonymously():
    """No oracle field at all — the shape of every certification we made before today."""
    with pytest.raises( VertexEnvError ) as exc:
        assert_certifications_are_provenanced( { "narnia-1": { "evidence": "it returned 200" } } )
    assert "narnia-1" in str( exc.value ) and "'oracle'" in str( exc.value )


def test_an_empty_evidence_field_is_refused():
    """An empty value is absence wearing a value's clothing — the same bug, one field over."""
    with pytest.raises( VertexEnvError ) as exc:
        assert_certifications_are_provenanced( {
            "narnia-1": { "oracle": "rawPredict", "evidence": "" }
        } )
    assert "'evidence'" in str( exc.value )


def test_the_public_helper_refuses_an_unevidenced_oracle_directly():
    """
    Reached only through the PUBLIC door. assert_certifications_are_provenanced catches
    an empty evidence field first, so this branch is dead from inside the module — but
    the helper is the entry point any future certification tooling will call, and there
    it is live. Coverage found it; without this test it would be an unproven guard on
    the exact surface the next seat will use.
    """
    with pytest.raises( VertexEnvError ) as exc:
        assert_region_oracle_is_admissible( "rawPredict", "" )
    assert "NO EVIDENCE" in str( exc.value )


def test_evidence_must_corroborate_the_oracle_it_names():
    """An oracle field that no evidence corroborates is decoration, not provenance."""
    with pytest.raises( VertexEnvError ) as exc:
        assert_region_oracle_is_admissible( "rawPredict", "I checked and it seemed fine" )
    assert "does not name the oracle" in str( exc.value )


def test_a_metadata_get_cannot_certify_a_region_either():
    """
    The ORIGINAL liar, still refused. It answered 200 for us-central1 — the region that
    ate three revisions of this design.
    """
    with pytest.raises( VertexEnvError ):
        assert_region_oracle_is_admissible( "publisherModel-metadata-GET", "GET .../models/x -> 200 GA" )


def test_rawpredict_is_the_only_admissible_oracle():
    """
    A one-element allowlist is a claim about EVERY instrument we have met. It is meant
    to be widened only by someone who has read why it is one element long.
    """
    assert ADMISSIBLE_REGION_ORACLES == ( "rawPredict", )


def test_a_real_rawpredict_certification_is_admitted():
    """
    POSITIVE CONTROL — without it, every refusal above is unattributable. A guard that
    refuses everything is indistinguishable from a guard that is broken.
    """
    assert assert_region_oracle_is_admissible(
        "rawPredict", "POST .../locations/global/...:rawPredict -> 200"
    ) is None
    assert assert_certifications_are_provenanced( VERTEX_REGION_CERTIFICATIONS ) is None


def test_the_shipped_certification_names_its_instrument():
    """The one region we certified must itself survive the guard we just built."""
    assert VERTEX_REGION_CERTIFICATIONS[ "global" ][ "oracle" ] == "rawPredict"
    assert "rawPredict" in VERTEX_REGION_CERTIFICATIONS[ "global" ][ "evidence" ]


def test_the_allowlist_is_derived_from_the_certifications_not_restated():
    """
    CERTIFIED_VERTEX_REGIONS is DERIVED from the map the import-time guard validated.
    Restating it as a second literal would let a region be enforced that was never
    certified — the drift this whole module exists to prevent.
    """
    assert CERTIFIED_VERTEX_REGIONS == tuple( VERTEX_REGION_CERTIFICATIONS )


# ── AC-D2 completeness: the FUNCTION leg of the coverage mandate ───────────────────

def test_quick_smoke_test_actually_executes( capsys ):
    """
    THE 100% MANDATE IS LINE *AND BRANCH* **AND FUNCTION**, and `quick_smoke_test()` was
    the one function in vertex_env.py that NOTHING ever called: pytest does not run it,
    and `python -m cosa.utils.vertex_env` is not wired into any suite or CI step.

    That is precisely the shape of `modules.bats` — a well-written block of assertions
    sitting in the tree, read like a guard, cited like a guard, executed never. It was
    at 79% line coverage for exactly this reason, and the missing 21% was ALL of it.

    So the suite calls it. It is self-contained (in-memory env mappings, no network, no
    GCP, no mutation), it re-proves each guard's failure branch independently of the
    tests above, and it now fails the build if it ever rots.
    """
    quick_smoke_test()

    out = capsys.readouterr().out
    assert "vertex_env smoke test PASSED" in out
    # it must have exercised the guards, not merely the happy path
    assert "refuses to launch on VERTEX_REGION_CLAUDE_4_8_OPUS" in out
    assert "refuses to launch on GOOGLE_APPLICATION_CREDENTIALS" in out
    assert "refuses to launch on project disagreement"          in out
    assert "refuses to launch with no project"                  in out


# ---------------------------------------------------------------------------
# C1 / OSQ-6 — the guards in the RIGHT PROCESS, unit half.
#
# Rio's C1 exploit, restated as the spec these tests enforce: a tainted server
# env holding VERTEX_REGION_CLAUDE_4_8_OPUS=us-east5 → the launcher shell is
# clean → assert_no_hostile_env PASSES (wrong process) → `-e` adds and subtracts
# nothing → the pane inherits it → Opus alone routes to us-east5, runs, bills,
# logs nothing. The guard was green because it was checking a room the model
# was never in. These functions are the two rooms the model IS in: the tmux
# SERVER's global env (OSQ-6) and the PANE's own env (§5c row 2).
# ---------------------------------------------------------------------------

def test_parse_reads_key_value_lines():
    parsed = parse_tmux_global_env( "PATH=/usr/bin\nCLAUDE_CODE_USE_VERTEX=1\n" )
    assert parsed == { "PATH": "/usr/bin", "CLAUDE_CODE_USE_VERTEX": "1" }


def test_parse_excludes_unset_markers():
    """`-KEY` is the server saying "unset" — exactly the state the guard wants."""
    parsed = parse_tmux_global_env( "-CLAUDE_CODE_USE_VERTEX\nPATH=/usr/bin\n" )
    assert "CLAUDE_CODE_USE_VERTEX" not in parsed
    assert parsed == { "PATH": "/usr/bin" }


def test_parse_preserves_values_containing_equals():
    """An env value may itself carry '=' — split once, keep the rest intact."""
    parsed = parse_tmux_global_env( "LESS=-R --mouse=on\nA=b=c=d" )
    assert parsed[ "LESS" ] == "-R --mouse=on"
    assert parsed[ "A" ]    == "b=c=d"


def test_parse_fails_loud_on_an_unparseable_line():
    """
    A line that is neither KEY=value nor -KEY is an INSTRUMENT failure. Silently
    skipping it would wave a hostile variable through the OSQ-6 check — "I could
    not parse" must never be reported as "the server is clean."
    """
    with pytest.raises( VertexEnvError ) as exc:
        parse_tmux_global_env( "GARBAGE WITHOUT ANY DELIMITER" )
    assert "Cannot parse" in str( exc.value )


def test_parse_of_empty_output_is_an_empty_mapping():
    """
    Empty output parses to {} — but whether emptiness is TRUSTWORTHY is the
    caller's burden (a failed tmux command and a clean server both print
    nothing). The docstring says so; the launcher must check the exit status.
    """
    assert parse_tmux_global_env( "" ) == {}


def test_a_clean_server_env_passes():
    """POSITIVE CONTROL — a guard that refuses everything is indistinguishable from a broken one."""
    assert assert_server_env_is_vertex_free( { "PATH": "/usr/bin", "SHELL": "/bin/bash" } ) is None


@pytest.mark.parametrize( "taint_key", SERVER_TAINT_REFUSAL_KEYS )
def test_every_refusal_key_in_the_server_env_refuses( taint_key ):
    """Parametrized over the WHOLE refusal set — a listed-but-unguarded key is impossible."""
    with pytest.raises( VertexEnvError ) as exc:
        assert_server_env_is_vertex_free( { taint_key: "anything" } )
    assert taint_key in str( exc.value )


def test_rios_exploit_is_dead_a_frozen_per_model_override_refuses():
    """
    THE C1 EXPLOIT, VERBATIM: VERTEX_REGION_CLAUDE_4_8_OPUS=us-east5 frozen into
    the server env — launcher shell clean, every launcher-side guard green —
    must now refuse AT THE SERVER CHECK, naming the key.
    """
    with pytest.raises( VertexEnvError ) as exc:
        assert_server_env_is_vertex_free( { "VERTEX_REGION_CLAUDE_4_8_OPUS": "us-east5" } )
    message = str( exc.value )
    assert "VERTEX_REGION_CLAUDE_4_8_OPUS" in message
    assert "TAINTED" in message


def test_all_server_offenders_are_named_not_just_the_first():
    with pytest.raises( VertexEnvError ) as exc:
        assert_server_env_is_vertex_free( {
            "CLAUDE_CODE_USE_VERTEX"    : "1",
            "ANTHROPIC_VERTEX_BASE_URL" : "https://evil",
        } )
    message = str( exc.value )
    assert "CLAUDE_CODE_USE_VERTEX" in message and "ANTHROPIC_VERTEX_BASE_URL" in message


def test_server_remediation_is_surgical_never_a_kill():
    """
    The remediation must be per-key `set-environment -g -u` — NEVER kill-server.
    This fleet died five times on 2026-07-14 from a kill that "knew" its target.
    An error message that teaches the reader to reach for kill-server is a
    fleet-killer with good intentions.
    """
    with pytest.raises( VertexEnvError ) as exc:
        assert_server_env_is_vertex_free( { "CLAUDE_CODE_USE_VERTEX": "1" } )
    message = str( exc.value )
    assert "tmux set-environment -g -u CLAUDE_CODE_USE_VERTEX" in message
    assert "kill-server" not in message


def test_server_blast_radius_is_stated_in_the_error():
    """
    Mr. Radio's rider (2026-07-15): the tainted-server refusal blocks EVERY
    launch on the socket until cleansed — that consequence must be IN the error
    text, visible at firing time, not discovered by the third blocked session.
    """
    with pytest.raises( VertexEnvError ) as exc:
        assert_server_env_is_vertex_free( { "CLAUDE_CODE_USE_VERTEX": "1" } )
    assert "BLAST RADIUS" in str( exc.value )


def test_an_empty_valued_server_key_is_not_an_offender():
    """
    KEY= (present, empty) follows the module's established truthiness convention
    (assert_no_hostile_env, same choice): an empty value is absence wearing a
    value's clothing, and refusing on it would fire on a var someone explicitly
    blanked to DISABLE the toggle.
    """
    assert assert_server_env_is_vertex_free( { "CLAUDE_CODE_USE_VERTEX": "" } ) is None


def test_the_refusal_set_is_derived_and_disjoint():
    """SERVER_TAINT_REFUSAL_KEYS is toggle + hostile, no duplicates — derived, not restated."""
    assert SERVER_TAINT_REFUSAL_KEYS == VERTEX_SESSION_KEYS + HOSTILE_ENV_KEYS
    assert len( SERVER_TAINT_REFUSAL_KEYS ) == len( set( SERVER_TAINT_REFUSAL_KEYS ) )


# A pane env exactly as a faithful launcher builds it: everything compose emits,
# nothing else. Derived from compose itself — never restated.
def _faithful_vertex_pane():
    return dict( compose_vertex_env( env=CLEAN_ENV ) )


def test_the_vertex_pane_guard_passes_on_a_faithful_pane():
    """POSITIVE CONTROL FIRST — no refusal below is attributable until this passes."""
    assert pane_guard( env=_faithful_vertex_pane(), vertex_path=True ) is None


def test_the_max_pane_guard_passes_on_a_clean_pane():
    assert pane_guard( env={ "PATH": "/usr/bin" }, vertex_path=False ) is None


def test_the_pane_guard_catches_the_silent_scrub_failure():
    """
    ARNOLD'S F4, CLOSED: the launcher derives the unset list behind 2>/dev/null —
    if that derivation silently dies, the pane is never scrubbed and nothing
    notices. The guard runs in the SAME shell after the unset, so a surviving
    key has exactly one meaning: the scrub did not happen.
    """
    tainted = { **_faithful_vertex_pane(), "GOOGLE_APPLICATION_CREDENTIALS": "/tmp/other.json" }
    with pytest.raises( VertexEnvError ) as exc:
        pane_guard( env=tainted, vertex_path=True )
    message = str( exc.value )
    assert "GOOGLE_APPLICATION_CREDENTIALS" in message
    assert "scrub" in message.lower()


def test_the_max_pane_guard_catches_the_toggle_key():
    """
    OSQ-6'S VICTIM, GUARDED AT LAST: a Max pane carrying CLAUDE_CODE_USE_VERTEX=1
    (frozen server env, failed scrub) dies HERE — before the first metered token —
    instead of being silently billed for a toggle it never asked for.
    """
    with pytest.raises( VertexEnvError ) as exc:
        pane_guard( env={ "CLAUDE_CODE_USE_VERTEX": "1" }, vertex_path=False )
    assert "CLAUDE_CODE_USE_VERTEX" in str( exc.value )


def test_the_max_pane_guard_catches_a_forged_model_pin():
    """C5's forgery, at runtime: a stale pin on a MAX pane is a silent model substitution."""
    with pytest.raises( VertexEnvError ) as exc:
        pane_guard( env={ "ANTHROPIC_DEFAULT_OPUS_MODEL": "claude-opus-4-0" }, vertex_path=False )
    assert "ANTHROPIC_DEFAULT_OPUS_MODEL" in str( exc.value )


@pytest.mark.parametrize( "toggle_key", VERTEX_SESSION_KEYS )
def test_the_vertex_pane_guard_is_the_p0_detector( toggle_key ):
    """
    THE P0 AS A RUNTIME GUARD, per missing key: a --vertex pane whose toggle key
    never arrived (the -e forward failed, or the scrub ate it — the seam defect)
    REFUSES TO START instead of running on Max under a metered-billing banner.
    """
    pane = _faithful_vertex_pane()
    del pane[ toggle_key ]
    with pytest.raises( VertexEnvError ) as exc:
        pane_guard( env=pane, vertex_path=True )
    assert toggle_key in str( exc.value )


def test_the_vertex_pane_guard_rejects_a_toggle_value_compose_never_emitted():
    """compose emits exactly '1'. Any other value has foreign provenance — refuse it."""
    pane = { **_faithful_vertex_pane(), "CLAUDE_CODE_USE_VERTEX": "true" }
    with pytest.raises( VertexEnvError ) as exc:
        pane_guard( env=pane, vertex_path=True )
    assert "compose_vertex_env" in str( exc.value )


def test_the_vertex_pane_guard_rejects_an_uncertified_region():
    """A pane whose CLOUD_ML_REGION is the dead region must refuse — same allowlist, right process."""
    pane = { **_faithful_vertex_pane(), "CLOUD_ML_REGION": "us-central1" }
    with pytest.raises( VertexEnvError ) as exc:
        pane_guard( env=pane, vertex_path=True )
    assert "not a CERTIFIED Vertex region" in str( exc.value )


def test_the_vertex_pane_guard_rejects_an_altered_model_pin():
    """A --vertex pane running an unpinned or re-pinned model is a silent substitution."""
    pane = { **_faithful_vertex_pane(), "ANTHROPIC_DEFAULT_OPUS_MODEL": "claude-opus-4-7" }
    with pytest.raises( VertexEnvError ) as exc:
        pane_guard( env=pane, vertex_path=True )
    assert "ANTHROPIC_DEFAULT_OPUS_MODEL" in str( exc.value )


def test_the_vertex_pane_guard_rejects_a_missing_model_pin():
    """Absence and alteration are the same defect: the pane is not what compose built."""
    pane = _faithful_vertex_pane()
    del pane[ "ANTHROPIC_DEFAULT_HAIKU_MODEL" ]
    with pytest.raises( VertexEnvError ) as exc:
        pane_guard( env=pane, vertex_path=True )
    assert "ANTHROPIC_DEFAULT_HAIKU_MODEL" in str( exc.value )


def test_the_pane_guard_defaults_to_the_real_process_environment( monkeypatch ):
    """
    The env=None default is the PRODUCTION path — the pane passes nothing. Prove
    it reads os.environ by making os.environ hostile and watching it fire.
    """
    for key in MAX_PANE_UNSET_KEYS:
        monkeypatch.delenv( key, raising=False )
    assert pane_guard( vertex_path=False ) is None

    monkeypatch.setenv( "CLAUDE_CODE_USE_VERTEX", "1" )
    with pytest.raises( VertexEnvError ):
        pane_guard( vertex_path=False )


@pytest.mark.parametrize( "disarm,replacement,expected", [
    ( "assert_no_hostile_env",     lambda *a, **k: None,        "guard did not fire" ),
    ( "assert_project_agreement",  lambda *a, **k: None,        "project-disagreement guard did not fire" ),
    # NB: _require resolves BOTH the project and the region, so a blunt `lambda: "proj-x"`
    # also hijacks the region and the certification guard fires FIRST — the branch under
    # test never runs and the test fails for the wrong reason. Fall back to the env value
    # when there is one; only the ABSENT project gets defaulted. (My first version got
    # this wrong, and the red told me so.)
    ( "_require",                  lambda env, key: env.get( key ) or "proj-x",
                                                                "missing-project guard did not fire" ),
] )
def test_the_smoke_test_itself_fails_loud_when_a_guard_is_disarmed(
    monkeypatch, disarm, replacement, expected
):
    """
    MY OWN LAW, RECURSED ONE LEVEL DOWN: is the SMOKE TEST decorative?

    quick_smoke_test() asserts each guard fires. But its own failure branches — the
    `raise AssertionError("... guard did not fire")` lines — never execute while the
    guards work, so NOTHING had ever proven the smoke test would NOTICE a guard going
    missing. A smoke test that cannot report a failure is the same class of object as a
    bats file nobody runs: it prints a reassuring "PASSED" either way.

    So: disarm each guard in turn and demand the smoke test SCREAMS. This covers those
    failure branches with a real behavioural assertion instead of a `# pragma: no cover`
    — which would have been the tidy way to HIDE the fact that nobody had ever checked.
    Coverage bought with a pragma is coverage you did not earn.
    """
    monkeypatch.setattr( vertex_env, disarm, replacement )

    with pytest.raises( AssertionError, match=expected ):
        quick_smoke_test()
