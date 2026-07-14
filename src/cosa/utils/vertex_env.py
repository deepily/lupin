"""
Vertex / Model Garden per-session toggle — environment composition and guards.

Design: src/rnd/v0.1.9/2026.07.13-vertex-model-garden-toggle-search-and-logging.md

WHY THIS IS PYTHON AND NOT BASH (§5e): the Lupin coverage mandate is 100% lines
AND branches AND functions. Bash has no branch-coverage instrument, so testing a
shell guard via its happy path and reporting "100%" is coverage theatre — it
walks the success path while the *guards*, the only thing standing between the
user and a silently mis-billed project, are exactly the branches that go
unmeasured. An unproven guard is decoration. The guards live here, where every
failure branch is red-first testable; the shell is a thin wrapper.

CERTIFY vs ENFORCE (§5c) — the load-bearing distinction:

    CERTIFY a region  ONCE, out of band   `rawPredict` -> 200.  Costs money.
    ENFORCE a region  every launch        equality + a calibrated free probe.  $0.

The only truthful region oracle is a real inference call, and it costs money.
Therefore A FREE LAUNCH-TIME REGION PROBE CANNOT EXIST. This module does NOT
re-derive the region; it ENFORCES a constant that was certified once. The
publisher-model metadata endpoint is deliberately NOT used: it returns 200 for
a region that cannot serve the model and 403 for one that can — the guard built
to stop the region trap would have opened the gate for it (§7).

The set of instruments that may NOT certify a region has grown once already (the
MaaS OpenAI-compat endpoint, 2026-07-13 — see the certification map below). So the
certification is no longer a bare tuple of strings that anyone can widen: every
region must NAME the instrument that proved it, and that instrument is checked at
IMPORT TIME (assert_region_oracle_is_admissible). A proof is not a guard; the
paragraph you are reading is a proof, and the import-time call is the guard.
"""

import os


# The Vertex serving region. NOT LUPIN_GCP_REGION — that is the CONTAINER-DEPLOY
# region (Cloud Run / Artifact Registry), and the model is not servable there.
# Two different concepts that shared a word, and now hold different values (§4a-ter).
VERTEX_REGION_ENV_KEY = "LUPIN_VERTEX_REGION"

# C2 — THE ALLOWLIST THE WORD "ENFORCE" WAS STANDING IN FOR.
#
# This module's docstring claimed it "enforces a constant certified once." It did
# not. LUPIN_VERTEX_REGION=us-central1 composed cleanly and exited 0 — the DEAD
# region, where claude-opus-4-8 is NOT SERVABLE (rawPredict -> 400). I wrote the
# certify-vs-enforce doctrine and then shipped a module that did neither.
#
# A region may appear here ONLY after a rawPredict returned 200 from it. Not a
# metadata GET (returns 200 for us-central1, which cannot serve). Not a quota row
# (there is a web-search allocation in us-central1, for a model that cannot run
# there). Not a flatPath. A LISTING IS NOT A CAPABILITY.
#
#   global       rawPredict -> 200   SERVES, and has working quota.  CERTIFIED.
#   us-east5     rawPredict -> 429   Servable but QUOTA-STARVED — deliberately NOT
#                                    certified: it would fail under any real load.
#   us-central1  rawPredict -> 400   NOT SERVABLE. The region this design once froze.
#   us           rawPredict -> 501   An access-scope word from the Model Garden form,
#                                    not an API location.
#
# ---------------------------------------------------------------------------
# WHICH INSTRUMENTS MAY CERTIFY A REGION — and the one that lied on 2026-07-13
# ---------------------------------------------------------------------------
#
# A region oracle is admissible only if it CAN COME OUT OTHERWISE ON THE REGION
# AXIS. Most Vertex surfaces cannot: they answer a question about the MODEL and let
# the region ride along in the URL path, unread.
#
# ADMISSIBLE — rawPredict. It reaches the serving stack for locations/{REGION} and
# 400s when the model cannot run there. It discriminates on the axis we are asking about.
#
# INADMISSIBLE — the MaaS OpenAI-COMPAT ENDPOINT. Newest of the family, and the most
# convincing, because it looks exactly like a real inference call:
#
#     POST /v1/projects/{P}/locations/{REGION}/endpoints/openapi/chat/completions
#
# IT IGNORES ITS OWN locations/{REGION} PATH SEGMENT. Measured (deepseek-v3.2-maas):
#
#     global       -> 200, 1418 bytes, content "OK"
#     us-central1  -> 200, 1418 bytes, content "OK"   <- the DEAD region
#     narnia-1     -> 200, 1418 bytes, content "OK"   <- A REGION THAT DOES NOT EXIST
#     acme/bogus-model @ narnia-1 -> 404
#
# BYTE-IDENTICAL across a real, a dead, and a FICTIONAL region. The MODEL axis
# discriminates; the REGION axis is BLIND. And the TELL is in the 404 body, which
# says "Ensure ... the model is available in the specified region" — IT CLAIMS
# REGION-SENSITIVITY IN ITS ERROR TEXT WHILE BEING BLIND TO REGION IN ITS BEHAVIOUR.
# An error code answering a question nobody asked. DO NOT CERTIFY A REGION WITH IT.
#
# (NOT retroactive: CERTIFIED_VERTEX_REGIONS was built from rawPredict, which
# genuinely 400s on us-central1. This is a trap for FUTURE work, so it is guarded
# below rather than merely written down — a proof is not a guard.)
#
# CONSUMER HAZARDS, if anything downstream ever CALLS this endpoint (calling it is
# fine; only certifying a REGION with it is not). Both measured on the same probe:
#
#   1. CoT SPLICE. openai/gpt-oss-120b-maas streams a SECOND channel,
#      `delta.reasoning_content` — the model's raw chain-of-thought (807 chars on
#      our probe). deepseek streams none. ANY CLIENT THAT NAIVELY CONCATENATES ALL
#      DELTAS SPLICES THE MODEL'S CoT INTO THE USER-VISIBLE ANSWER. Filter on the
#      FIELD NAME (`delta.content`); never on "whatever the deltas contain."
#
#   2. PHANTOM PREAMBLE. The prompt you send is not the prompt the model sees. An
#      identical 9-token user message billed prompt_tokens=9 (deepseek) vs 72
#      (gpt-oss, 64 cached) — ~63 tokens of system preamble we never wrote. You are
#      billed for tokens you did not author, so never compute cost from YOUR count.
ADMISSIBLE_REGION_ORACLES = (
    "rawPredict",
)

# Evidence fragments that PROVE the wrong instrument was used. Kept narrow and
# unambiguous on purpose: a fragment that also appears in a rawPredict URL would
# make this guard fire on a VALID certification, which is the "guard that fires on
# a correct configuration" bug (C4) — the one that teaches people to disable guards.
REGION_BLIND_EVIDENCE_FRAGMENTS = (
    "endpoints/openapi",   # the MaaS OpenAI-compat path — ignores locations/{REGION}
    "chat/completions",    # ...and the same surface named by its other half
)

CERTIFICATION_FIELDS = ( "oracle", "evidence" )

# THE GUARD (see assert_region_oracle_is_admissible): a region cannot enter this
# map anonymously. It must NAME the instrument that certified it, and that
# instrument is checked at IMPORT TIME — so a seat that certifies `us-central1`
# from an OpenAI-compat 200 cannot even load the module, let alone launch.
VERTEX_REGION_CERTIFICATIONS = {
    "global" : {
        "oracle"   : "rawPredict",
        "evidence" : (
            "POST .../locations/global/publishers/anthropic/models/"
            "claude-opus-4-8:rawPredict -> 200 (2026-07-13)"
        ),
    },
}

# Per-model region overrides shipped in the Claude Code binary (15 of them). Each one
# overrides CLOUD_ML_REGION *for a single model* — so one inherited var routes Opus alone
# to another region, where it runs, bills, and logs nothing, while every other model
# behaves normally. The region trap wearing a disguise.
#
# C3 — THIS TUPLE IS A HARVEST FROM SOMEONE ELSE'S RELEASE ARTIFACT, AND A HARVEST HAS A DATE.
#
# The parametrized guard suite proves every key IN this tuple is guarded. It proves NOTHING
# about a key that exists in the WORLD but not in the tuple — and that is the whole risk,
# because the tuple is a point-in-time `strings` scrape of a binary we do not control. Note
# what is in it: CLAUDE_5_SONNET, but no CLAUDE_5_OPUS. Correct today; one release from wrong.
# A completeness claim that cannot fail is a wish with good grammar.
#
# So this tuple's completeness is RE-DERIVED from the shipped binary on every run
# (test_vertex_env_completeness.py), and that scrape FAILS — never skips — when it cannot see
# the binary: a skipped completeness check and a passing one are indistinguishable in a
# 9,000-test run. The re-derivation is the GUARD. The calibration below is a RECORD, not a
# guard: it says which release this harvest was taken from, so that when the drift test goes
# red the reader can see, in one line, what changed underneath them.
#
# The calibration is deliberately NOT asserted against the running binary. A CC upgrade that
# does not touch the key set is a VALID configuration, and a guard that fires on a valid
# configuration teaches people to disable guards (C4, one bucket over). Only DRIFT IN THE KEYS
# is an error; a drift in the version number is merely news.
PER_MODEL_REGION_OVERRIDES_CALIBRATION = {
    "cc_version" : "2.1.209",
    "harvested"  : "2026-07-14",
    "instrument" : "strings $(readlink -f $(which claude)) | grep -oE 'VERTEX_REGION_CLAUDE_[A-Z0-9_]+'",
}

PER_MODEL_REGION_OVERRIDES = (
    "VERTEX_REGION_CLAUDE_3_5_HAIKU",
    "VERTEX_REGION_CLAUDE_3_5_SONNET",
    "VERTEX_REGION_CLAUDE_3_7_SONNET",
    "VERTEX_REGION_CLAUDE_4_0_OPUS",
    "VERTEX_REGION_CLAUDE_4_0_SONNET",
    "VERTEX_REGION_CLAUDE_4_1_OPUS",
    "VERTEX_REGION_CLAUDE_4_5_OPUS",
    "VERTEX_REGION_CLAUDE_4_5_SONNET",
    "VERTEX_REGION_CLAUDE_4_6_OPUS",
    "VERTEX_REGION_CLAUDE_4_6_SONNET",
    "VERTEX_REGION_CLAUDE_4_7_OPUS",
    "VERTEX_REGION_CLAUDE_4_8_OPUS",
    "VERTEX_REGION_CLAUDE_5_SONNET",
    "VERTEX_REGION_CLAUDE_FABLE_5",
    "VERTEX_REGION_CLAUDE_HAIKU_4_5",
)

# §5c.2 is "CLEAR **or ASSERT**", and the distinction is load-bearing:
#
#   ASSERTABLE  — GOOGLE_CLOUD_PROJECT / GCLOUD_PROJECT name a project, so they can
#                 be COMPARED to the resolved one. Present-and-agreeing is harmless;
#                 present-and-disagreeing bills someone else, silently. -> assert.
#
#   UNASSERTABLE — GOOGLE_APPLICATION_CREDENTIALS points at a service-account KEY
#                 FILE whose project we cannot know without reading and trusting it.
#                 There is nothing to compare it against, so it cannot be asserted —
#                 only cleared. It is the sharpest of the three precisely because it
#                 defeats the project guard from OUTSIDE the project's namespace.
#
# Collapsing these two categories (banning all three) was a real bug, caught by the
# red-first suite: it made a HARMLESS, AGREEING GOOGLE_CLOUD_PROJECT abort the launch.
# A guard that fires on a correct configuration teaches people to disable guards.
ASSERTABLE_PROJECT_OVERRIDES = (
    "GOOGLE_CLOUD_PROJECT",
    "GCLOUD_PROJECT",
)

UNASSERTABLE_PROJECT_OVERRIDES = (
    "GOOGLE_APPLICATION_CREDENTIALS",
)

# C4 — the assertable/unassertable split, ONE BUCKET OVER. I fixed it for the
# project variables and did not sweep the sibling category: an ANTHROPIC_MODEL that
# AGREES with our pin is harmless, and aborting on it is the same "guard that fires
# on a valid configuration" bug. My own rule — grep for the CLASS, not the line you
# fixed — broken by me, in the fix where I coined it.
#
# These are compared against the pin they would override, not banned.
ASSERTABLE_MODEL_OVERRIDES = {
    "ANTHROPIC_MODEL"            : "ANTHROPIC_DEFAULT_OPUS_MODEL",
    "ANTHROPIC_SMALL_FAST_MODEL" : "ANTHROPIC_DEFAULT_HAIKU_MODEL",
}

ENDPOINT_SUBVERTERS = (
    "ANTHROPIC_VERTEX_BASE_URL",    # redirects the endpoint
    "CLAUDE_CODE_SKIP_VERTEX_AUTH", # bypasses auth
)

# Everything the --vertex path must SCRUB from the pane before `claude` starts.
# "Scrub, don't omit" (F-A7): a positive tmux -e allowlist ADDS keys and SUBTRACTS
# NOTHING, so an unlisted key inherits whatever the frozen tmux server env holds.
# Omission is not subtraction.
HOSTILE_ENV_KEYS = (
    PER_MODEL_REGION_OVERRIDES
    + UNASSERTABLE_PROJECT_OVERRIDES
    + ENDPOINT_SUBVERTERS
)

# Everything the PANE must be cleansed of, or have corrected, before `claude` starts.
# C1: the guard runs in the LAUNCHER's process; `claude` runs in the PANE, on the
# FROZEN tmux server env. A guard that fires in the wrong process is not a guard
# (F-A10) — and I closed F-A10 in the doc, then rebuilt it in the code.
# The pane scrub is DELIBERATELY WIDER than the launcher guard set.
#
# In the LAUNCHER we can ASSERT the project vars (compare them to the resolved
# project). In the PANE we cannot: the pane inherits the FROZEN tmux server env,
# whose values the launcher never saw and cannot vouch for. A stale
# GOOGLE_CLOUD_PROJECT sitting on a server started hours ago TAKES PRECEDENCE over
# ANTHROPIC_VERTEX_PROJECT_ID and bills the wrong GCP project, silently, with every
# launcher-side guard green.
#
# So the pane gets them UNSET outright, leaving ANTHROPIC_VERTEX_PROJECT_ID (which we
# forward explicitly via -e) as the single authority. No precedence fight to lose.
PANE_UNSET_KEYS = (
    HOSTILE_ENV_KEYS
    + tuple( ASSERTABLE_MODEL_OVERRIDES )
    + ASSERTABLE_PROJECT_OVERRIDES
)

# The three variables that PUT a session on Vertex. A Max session must never carry
# them — and a tmux server born from a Vertex shell hands them to EVERY later session
# on that socket, Max ones included (OSQ-6, verified live: a Max pane on a tainted
# server read CLAUDE_CODE_USE_VERTEX=1).
#
# That is the INVERSE of the hole this module was written to close, and it is WORSE:
# the other mis-bills a session that already opted into billing; this one bills a
# session that NEVER ASKED. So the launcher scrubs these from the pane on EVERY path,
# and only --vertex re-adds them, explicitly, via `-e`.
#
#   SCRUB ALWAYS. OPT IN DELIBERATELY.
VERTEX_SESSION_KEYS = (
    "CLAUDE_CODE_USE_VERTEX",
    "CLOUD_ML_REGION",
    "ANTHROPIC_VERTEX_PROJECT_ID",
)

# Model pins. Dated snapshots use an "@" version separator on Vertex — NOT the
# hyphenated first-party form. Without the pins, the `opus` alias resolves to an
# OLDER Opus. And a pin alone is not enough: ANTHROPIC_MODEL overrides it, which
# is why ASSERTABLE_MODEL_OVERRIDES is compared against it. A pin you can override
# from the environment is a preference, not a pin.
MODEL_PINS = {
    "ANTHROPIC_DEFAULT_OPUS_MODEL"   : "claude-opus-4-8",
    "ANTHROPIC_DEFAULT_SONNET_MODEL" : "claude-sonnet-4-6",
    "ANTHROPIC_DEFAULT_HAIKU_MODEL"  : "claude-haiku-4-5@20251001",
}

# P0 — THE SCRUB ATE THE FEATURE. The set a pane must be cleansed of DEPENDS ON THE PATH,
# and shipping ONE unconditional set is what made `--vertex` a lie.
#
# The launcher used to prepend `unset <PANE_UNSET_KEYS + VERTEX_SESSION_KEYS>` to the pane
# command ON BOTH PATHS. On the --vertex path it had just forwarded those exact three keys
# via `tmux -e`... and then the pane's own first command DELETED THEM. `--vertex` printed a
# METERED-BILLING banner and ran on Max.
#
# C1 (scrub the pane, not the launcher) and OSQ-6 (scrub on EVERY path, not just --vertex)
# are each CORRECT IN ISOLATION. The defect is their COMPOSITION with the `-e` forward —
# it lives in no single fix, only in the seam between two of them. RIGOR FAILS WHERE RELIEF
# LIVES: both were "done", both were green, and the green could not have come out otherwise
# (a pane that reads <unset> looks identical whether the hole is CLOSED or the feature is DEAD).
#
# It failed SAFE — no money burned. But THE BANNER LIED, AND THE BANNER IS WHAT A HUMAN TRUSTS.
# A guard that silently disables the feature it protects has not protected anything; it has
# just moved the failure somewhere nobody is looking.
#
# ---------------------------------------------------------------------------
# C5 (Rio, 2026-07-14) — THE PINS THEMSELVES ARE FORGEABLE, AND THE TEST HID IT.
# ---------------------------------------------------------------------------
#
# THE RULE, stated properly at last: EVERY KEY WE EMIT IS A KEY A TAINTED SERVER CAN FORGE.
# What --vertex hands the pane via `-e`, a frozen tmux server env can hand a MAX pane for
# free — so the MAX path must scrub EVERYTHING compose emits, not just the three toggle keys.
#
# MODEL_PINS were emitted by compose and scrubbed by NEITHER set. On the MAX path a stale
# ANTHROPIC_DEFAULT_OPUS_MODEL frozen into the tmux server rides straight into the pane and
# SILENTLY CHANGES WHICH MODEL THE SESSION RUNS — with every guard green, because no guard
# was looking. Not a billing leak; a MODEL SUBSTITUTION. Quieter, and harder to notice.
#
# AND THE TEST THAT EXISTED TO CATCH THIS SUBTRACTED THE ANSWER BEFORE ASKING THE QUESTION:
#
#     emitted = set( compose_vertex_env( env=CLEAN_ENV ) ) - set( MODEL_PINS )   # <-- !!
#     assert emitted == set( VERTEX_SESSION_KEYS )
#
# Its docstring said "a key we EMIT but never SCRUB is a key a tainted server can forge" —
# and then it removed, by name, the only keys for which that was true. A TEST WEAKENED UNTIL
# IT PASSED, wearing the docstring of the test that would have failed. Sixth guard-that-
# cannot-fail of this cascade, and it was sitting inside the fix for the fifth.
#
# On the --vertex path the pins are NOT scrubbed: we just forwarded them, and `-e` (session
# env) outranks the frozen server env. SCRUB ALWAYS WHAT IS HOSTILE. NEVER SCRUB WHAT YOU
# JUST FORWARDED. The path-dependence is the whole design, and it now covers every emitted key.
MAX_PANE_UNSET_KEYS = PANE_UNSET_KEYS + VERTEX_SESSION_KEYS + tuple( MODEL_PINS )


class VertexEnvError( RuntimeError ):
    """Raised when the Vertex environment cannot be composed safely. Fail loud."""


def assert_region_oracle_is_admissible( oracle, evidence ):
    """
    Refuse a region certification whose INSTRUMENT cannot see regions.

    This is the guard for the trap of 2026-07-13: the MaaS OpenAI-compat endpoint
    returns a BYTE-IDENTICAL 200 for a live region, the dead region, and a region
    that does not exist — while its own 404 body claims to check "the specified
    region". An error code answering a question nobody asked.

    The prose above the certification map warns about it. Prose does not run.
    THIS runs, at import, in every process that touches the toggle — so the honest
    mistake (certify a region from a 200 that could not have come out otherwise)
    is impossible rather than merely discouraged.

    Its limit, stated because a guard whose limit is unstated gets over-trusted:
    it cannot catch a LIE. A seat that runs the OpenAI-compat probe and then types
    oracle="rawPredict" defeats it. No guard can stop a fabrication; this one makes
    the mistake structural and forces the fabrication to be an explicit false
    statement, in a field that exists for no other purpose.

    Requires:
        - oracle and evidence are strings

    Ensures:
        - returns None when the oracle is admissible and the evidence corroborates it

    Raises:
        - VertexEnvError when the oracle is not in ADMISSIBLE_REGION_ORACLES, when
          the evidence is empty, when the evidence does not name the oracle it
          claims, or when the evidence carries the fingerprint of a region-blind surface
    """
    if oracle not in ADMISSIBLE_REGION_ORACLES:
        raise VertexEnvError(
            f"Refusing the region certification: '{oracle}' is not an admissible region oracle. "
            f"Admissible: {', '.join( ADMISSIBLE_REGION_ORACLES )}. A region oracle must be able "
            f"to COME OUT OTHERWISE ON THE REGION AXIS. The MaaS OpenAI-compat endpoint "
            f"(endpoints/openapi/chat/completions) cannot: it returned a byte-identical 200 for "
            f"'global', for the DEAD 'us-central1', and for the FICTIONAL 'narnia-1'. The metadata "
            f"GET cannot either (200 for a region that cannot serve). Neither can a quota row or a "
            f"flatPath. A LISTING IS NOT A CAPABILITY."
        )

    if not evidence:
        raise VertexEnvError(
            f"Refusing the region certification: oracle '{oracle}' was named with NO EVIDENCE. "
            f"An unevidenced certification is a claim, and this module exists because a claim "
            f"beat a measurement three revisions running. Record the request and what it returned."
        )

    if oracle not in evidence:
        raise VertexEnvError(
            f"Refusing the region certification: the evidence does not name the oracle it claims "
            f"('{oracle}'). Evidence: {evidence!r}. The evidence must record the call that was "
            f"actually made — an oracle field that no evidence corroborates is decoration."
        )

    for fragment in REGION_BLIND_EVIDENCE_FRAGMENTS:
        if fragment in evidence:
            raise VertexEnvError(
                f"Refusing the region certification: the evidence names '{fragment}' — the MaaS "
                f"OpenAI-compat surface, which IGNORES its own locations/{{REGION}} path segment. "
                f"Measured 2026-07-13: byte-identical 200s from a real region, a dead region, and "
                f"a region that does not exist. It certifies MODELS, never REGIONS. Certify with a "
                f"rawPredict that returned 200, or do not certify."
            )


def assert_certifications_are_provenanced( certifications ):
    """
    Refuse to LOAD when any certified region lacks admissible provenance.

    Called at import time, below. The allowlist is the surface a future seat will
    widen, so the guard belongs on the ACT OF WIDENING IT — not in a comment beside it.

    Requires:
        - certifications maps a region name to a record with 'oracle' and 'evidence'

    Ensures:
        - returns None when every region's provenance is admissible

    Raises:
        - VertexEnvError naming the offending REGION (the caller's mistake is a
          region, not a dict), with the instrument failure as the cause
    """
    for region, record in certifications.items():
        for field in CERTIFICATION_FIELDS:
            if field not in record or not record[ field ]:
                raise VertexEnvError(
                    f"Refusing the region certification for '{region}': the record has no "
                    f"'{field}'. A region may not be certified anonymously — name the instrument "
                    f"that proved it and what that instrument returned."
                )
        try:
            assert_region_oracle_is_admissible( record[ "oracle" ], record[ "evidence" ] )
        except VertexEnvError as error:
            raise VertexEnvError( f"Region '{region}': {error}" ) from error


# IMPORT-TIME. Not a test, not a comment — a load-bearing statement. A module that
# certifies a region from a region-blind instrument does not import, so it cannot
# launch, so it cannot bill. CERTIFIED_VERTEX_REGIONS is then DERIVED from the map
# it was validated against, which is why the two can never drift apart.
assert_certifications_are_provenanced( VERTEX_REGION_CERTIFICATIONS )

CERTIFIED_VERTEX_REGIONS = tuple( VERTEX_REGION_CERTIFICATIONS )


def _require( env, key ):
    """
    Read a required key from env, failing loud when absent or empty.

    Requires:
        - env is a mapping
        - key is a non-empty string

    Ensures:
        - returns the non-empty string value of env[ key ]

    Raises:
        - VertexEnvError if the key is absent or empty
    """
    value = env.get( key )
    if not value:
        raise VertexEnvError(
            f"{key} is not set. There is no safe default: guessing it would bill a project "
            f"nobody chose, in a region that may not serve the model."
        )
    return value


def assert_no_hostile_env( env ):
    """
    Refuse to launch when any variable that could silently subvert the toggle is present.

    These are PREFLIGHT guards: they run before the first token. A guard that fires
    after the billing event is not a guard.

    Requires:
        - env is a mapping of environment variables

    Ensures:
        - returns None when no hostile key is present

    Raises:
        - VertexEnvError naming EVERY offending key (not just the first — a caller
          who fixes one and re-runs should not discover the next one serially)
    """
    offenders = [ key for key in HOSTILE_ENV_KEYS if env.get( key ) ]
    if offenders:
        raise VertexEnvError(
            "Refusing to launch: these variables would silently subvert the Vertex toggle — "
            f"{', '.join( sorted( offenders ) )}. They override the region PER MODEL, steal "
            "project precedence, defeat the model pins, redirect the endpoint, or bypass auth. "
            "Unset them (the --vertex path scrubs them inside the pane; this guard catches the "
            "case where scrubbing did not happen)."
        )


def assert_project_agreement( env, project_id ):
    """
    Refuse to launch when any variable disagrees with the resolved project.

    GOOGLE_CLOUD_PROJECT / GCLOUD_PROJECT take precedence over
    ANTHROPIC_VERTEX_PROJECT_ID, so a mismatch bills a DIFFERENT project, silently.

    Requires:
        - env is a mapping; project_id is a non-empty string

    Ensures:
        - returns None when every project-bearing variable agrees with project_id

    Raises:
        - VertexEnvError on any disagreement
    """
    for key in ASSERTABLE_PROJECT_OVERRIDES:
        other = env.get( key )
        if other and other != project_id:
            raise VertexEnvError(
                f"Refusing to launch: {key}={other} disagrees with the resolved project "
                f"{project_id}. {key} takes PRECEDENCE, so this would bill a different "
                f"project — silently."
            )


def assert_region_is_certified( region ):
    """
    Refuse to launch on a region no rawPredict has ever certified.

    C2: the module previously ACCEPTED any string. `LUPIN_VERTEX_REGION=us-central1`
    composed cleanly and exited 0 — the region where the model is NOT SERVABLE. The
    word "enforce" in the docstring was doing the work an allowlist should have done.

    Requires:
        - region is a non-empty string

    Ensures:
        - returns None when region is in CERTIFIED_VERTEX_REGIONS

    Raises:
        - VertexEnvError naming the certified set, because a region that is merely
          LISTED, or merely has QUOTA, is not a region that RUNS
    """
    if region not in CERTIFIED_VERTEX_REGIONS:
        raise VertexEnvError(
            f"Refusing to launch: '{region}' is not a CERTIFIED Vertex region. Certified: "
            f"{', '.join( CERTIFIED_VERTEX_REGIONS )}. A region is certified ONLY by a rawPredict "
            f"that returned 200 — never by the publisher-model metadata endpoint (it returns 200 "
            f"for us-central1, which CANNOT SERVE the model), never by the MaaS OpenAI-compat "
            f"endpoint (endpoints/openapi/chat/completions: byte-identical 200s from a real, a "
            f"dead, and a FICTIONAL region — it is BLIND to the region in its own path), never by "
            f"a quota row, never by a flatPath. If you have certified a new region with a real "
            f"call, add it to VERTEX_REGION_CERTIFICATIONS with the instrument and what it returned "
            f"— the import-time guard will check the instrument."
        )


def assert_model_pin_agreement( env ):
    """
    Refuse to launch when a model override DISAGREES with the pin it would defeat.

    C4: present-and-AGREEING is harmless (ANTHROPIC_MODEL=claude-opus-4-8 is exactly
    what the pin asks for). Banning it outright was the same "guard that fires on a
    valid configuration" bug already fixed one bucket over, for the project variables.

    Requires:
        - env is a mapping

    Ensures:
        - returns None when every present override matches its pin

    Raises:
        - VertexEnvError on a disagreement, naming both values
    """
    for override_key, pin_key in ASSERTABLE_MODEL_OVERRIDES.items():
        value = env.get( override_key )
        if value and value != MODEL_PINS[ pin_key ]:
            raise VertexEnvError(
                f"Refusing to launch: {override_key}={value} DISAGREES with the pin "
                f"{pin_key}={MODEL_PINS[ pin_key ]}. {override_key} OVERRIDES the pin, so this "
                f"would silently run a different model than the one this session was authorized "
                f"and priced for."
            )


def pane_unset_keys( vertex_path ):
    """
    The keys the PANE must unset before `claude` starts — and the answer DEPENDS ON THE PATH.

    MAX path    -> scrub EVERYTHING, the three toggle keys included. A tmux server born
                   from a Vertex shell freezes CLAUDE_CODE_USE_VERTEX into its env and
                   hands it to every later session on that socket, Max ones included
                   (OSQ-6, verified live). That session never asked to be billed.

    VERTEX path -> scrub the HOSTILE / PRECEDENCE set ONLY. The three toggle keys are not
                   contamination here — THEY ARE THE FEATURE. They arrive via `tmux -e`,
                   which sets the SESSION environment and therefore outranks the frozen
                   server env: there is no precedence fight to lose, and nothing to re-add.
                   Scrubbing them here is what killed `--vertex`.

    The one-line rule this function exists to enforce:

        SCRUB ALWAYS WHAT IS HOSTILE. NEVER SCRUB WHAT YOU JUST FORWARDED.

    The decision lives in Python, not in the shell, for the same reason the guards do
    (§5e): this is a BRANCH, and bash has no branch-coverage instrument. An unmeasured
    branch in a billing path is how the last one hid.

    Requires:
        - vertex_path is a bool: True on the --vertex path, False on the Max path

    Ensures:
        - returns PANE_UNSET_KEYS on the --vertex path — disjoint from compose_vertex_env()
        - returns MAX_PANE_UNSET_KEYS on the Max path — a strict superset, adding the toggle keys
    """
    if vertex_path:
        return PANE_UNSET_KEYS
    return MAX_PANE_UNSET_KEYS


def compose_vertex_env( env=None, project_id=None, region=None ):
    """
    Compose the Vertex environment for ONE process, failing loud on any hazard.

    This ENFORCES a region that was CERTIFIED once by a rawPredict (§5c). It does
    NOT re-derive servability: the only truthful region oracle costs money, so a
    free launch-time region probe cannot exist, and the metadata endpoint LIES
    (200 for a region that cannot serve; 403 for one that can).

    Requires:
        - env is a mapping (defaults to os.environ)
        - project_id / region default to the resolver's values via the environment

    Ensures:
        - returns a dict of the exact variables to export for this process only
        - CLOUD_ML_REGION == the certified LUPIN_VERTEX_REGION
        - ANTHROPIC_VERTEX_PROJECT_ID == the resolved project
        - all three model pins present, Haiku in "@"-form

    Raises:
        - VertexEnvError on a missing project/region, a hostile variable, or a
          project disagreement
    """
    if env is None:
        env = os.environ

    resolved_project = project_id if project_id else _require( env, "LUPIN_GCP_PROJECT_ID" )
    resolved_region  = region     if region     else _require( env, VERTEX_REGION_ENV_KEY )

    assert_region_is_certified( resolved_region )
    assert_no_hostile_env( env )
    assert_project_agreement( env, resolved_project )
    assert_model_pin_agreement( env )

    composed = {
        "CLAUDE_CODE_USE_VERTEX"      : "1",
        "CLOUD_ML_REGION"             : resolved_region,
        "ANTHROPIC_VERTEX_PROJECT_ID" : resolved_project,
    }
    composed.update( MODEL_PINS )
    return composed


def format_dry_run( composed ):
    """
    Render the composed environment for --dry-run: compose, assert, print, launch nothing.

    Requires:
        - composed is a mapping of environment variables

    Ensures:
        - returns a newline-joined KEY=VALUE listing, sorted for stable diffing
    """
    return "\n".join( f"{key}={composed[ key ]}" for key in sorted( composed ) )


def quick_smoke_test():
    """Exercise the happy path and each guard's failure branch."""
    import cosa.utils.util as du

    du.print_banner( "vertex_env smoke test", prepend_nl=True )

    base = { "LUPIN_GCP_PROJECT_ID": "proj-x", VERTEX_REGION_ENV_KEY: "global" }

    composed = compose_vertex_env( env=base )
    assert composed[ "CLOUD_ML_REGION" ]             == "global"
    assert composed[ "ANTHROPIC_VERTEX_PROJECT_ID" ] == "proj-x"
    assert composed[ "ANTHROPIC_DEFAULT_HAIKU_MODEL" ] == "claude-haiku-4-5@20251001"
    print( "✓ composes the happy path" )

    for hostile in ( "VERTEX_REGION_CLAUDE_4_8_OPUS", "GOOGLE_APPLICATION_CREDENTIALS", "ANTHROPIC_MODEL" ):
        try:
            compose_vertex_env( env={ **base, hostile: "x" } )
            raise AssertionError( f"guard did not fire for {hostile}" )
        except VertexEnvError:
            print( f"✓ refuses to launch on {hostile}" )

    try:
        compose_vertex_env( env={ **base, "GOOGLE_CLOUD_PROJECT": "other" } )
        raise AssertionError( "project-disagreement guard did not fire" )
    except VertexEnvError:
        print( "✓ refuses to launch on project disagreement" )

    try:
        compose_vertex_env( env={ VERTEX_REGION_ENV_KEY: "global" } )
        raise AssertionError( "missing-project guard did not fire" )
    except VertexEnvError:
        print( "✓ refuses to launch with no project" )

    print( "\nvertex_env smoke test PASSED" )


if __name__ == "__main__":
    quick_smoke_test()
