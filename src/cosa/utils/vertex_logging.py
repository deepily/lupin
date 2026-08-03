"""
Vertex request-response logging — the verification harness (design §4 / cascade §C).

WHAT THIS MODULE IS FOR
-----------------------
`setPublisherModelConfig` has already been written and read back (2026-07-13, LRO
847218789178146816 -> done, no error). We know the CONFIG READS BACK. We do NOT know
that DATA ARRIVES. Those are different claims, and this module exists to prove the
second one — or to refuse to render a verdict at all.

THE LAW THIS MODULE ENCODES
---------------------------
BigQuery ingest LAGS. A "not found" is therefore NOT evidence of "not logged" — it may
merely be early. So:

    A NULL IS NOT EVIDENCE UNTIL THE INSTRUMENT IS PROVEN.
    And a null that CONFIRMS a suspicion sails through the checkpoint a contradicting
    one never would.

Consequently NO function here will ever return "not logged" from a bare SELECT. Every
negative verdict is gated on a CANARY — a known-good write, carrying a unique greppable
sentinel — having been SEEN in the SAME WINDOW in which the silence is trusted. If the
canary does not land, the verdict is INADMISSIBLE, never REFUTED. Fail loud, not quiet.

    An observation is evidence only if it could have come out otherwise.  (Rio)

A POSITIVE NEEDS NO CANARY. Presence proves itself; only ABSENCE needs a calibrated
instrument. That asymmetry is load-bearing throughout.

THE §4f TENSION, DISSOLVED
--------------------------
§4f mandates: assert on the ROW COUNT, never on a COLUMN — because
`requestResponseLoggingSchemaVersion` is output-only and versioned (v1/v2), so the row
shape is NOT knowable pre-flight, and naming a column turns a schema bump into a false
failure. But a sentinel needs to be FOUND, which sounds like it needs a column.

It does not. `TO_JSON_STRING(t)` serializes the WHOLE ROW whatever its schema, so

    SELECT COUNT(*) FROM `p.d.t` AS t WHERE STRPOS( TO_JSON_STRING( t ), @sentinel ) > 0

is simultaneously schema-agnostic (names ZERO columns — survives a v1 -> v2 bump) and
attributable (finds MY row, not somebody else's traffic). Sentinel attribution and the
no-columns rule were never in conflict.

Residual, stated rather than buried: if the payload lands BYTES-encoded or compressed,
TO_JSON_STRING base64s it and the sentinel will not match. That failure mode yields
INADMISSIBLE (canary unseen), NOT a false REFUTED. The instrument fails SAFE.

NO LIVE CALLS FROM THIS MODULE
------------------------------
Nothing here reaches the network. Every outbound edge is an injected callable
(`query_fn`, `clock`, `sleeper`). The default query function REFUSES. A live run is
composed by the caller, under explicit authorization, and the set of live calls it needs
is enumerable in advance — see `describe_live_calls()`.
"""

import re
import uuid


class VertexLoggingError( RuntimeError ):
    """Raised when the logging config or its verification cannot proceed safely. Fail loud."""


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# The log sink dataset. Vertex creates the table itself from a dataset-level outputUri
# (§4d) — so the TABLE NAME IS NOT OURS TO ASSUME. We discover it. This constant is the
# documented default, recorded for diagnosis, and is never used as a query target.
DEFAULT_LOG_DATASET        = "vertex_logging"
DOCUMENTED_DEFAULT_TABLE   = "request_response_logging"

# A table WE own, used to prove the READOUT is awake independently of whether Vertex has
# written anything. See `readout_positive_control_sql()`.
READOUT_CANARY_TABLE       = "harness_readout_canary"

SENTINEL_PREFIX            = "LUPIN-VLOG-"
SENTINEL_PATTERN           = re.compile( r"^LUPIN-VLOG-[0-9a-f]{12}$" )

# BigQuery has NO `global` location. Datasets live in REGIONS or MULTI-REGIONS (§4e).
# The rule rev. 4 wrote — "assert dataset location == $LUPIN_VERTEX_REGION" — is
# UNSATISFIABLE BY CONSTRUCTION once the Vertex SSOT is `global`. Same word, different
# universes. A shared name is not sameness.
BIGQUERY_ILLEGAL_LOCATIONS = ( "global", )

# CERTIFIED pairings ONLY. A pairing enters this table when it has been OBSERVED to work,
# never when it merely seems reasonable — the same certify-then-enforce doctrine
# vertex_env.CERTIFIED_VERTEX_REGIONS applies to regions. OSQ C-5 is CLOSED for (global, US)
# and remains open for every other pair.
CERTIFIED_LOCATION_PAIRINGS = {
    ( "global", "US" ) : (
        "2026-07-13: setPublisherModelConfig POSTed at locations/global -> 200; LRO "
        "847218789178146816 polled to done=True with NO error; fetchPublisherModelConfig "
        "read back enabled=true, samplingRate=1, outputUri=bq://<project>.vertex_logging "
        "against a US multi-region dataset. OSQ C-5 CLOSED for this pair."
    ),
}


# ---------------------------------------------------------------------------
# Verdicts
# ---------------------------------------------------------------------------

# The three-valued logic this whole module exists to protect. Two of them are the
# ordinary ones; the third is the one that keeps us honest.
VERDICT_PROVEN       = "PROVEN"        # the positive was OBSERVED. Needs no canary.
VERDICT_REFUTED      = "REFUTED"       # the null is ADMISSIBLE: the canary was seen, and the subject was not.
VERDICT_INADMISSIBLE = "INADMISSIBLE"  # the instrument never proved it was awake. NO verdict. Not a pass. Not a fail.

# What the readout itself looked like — separates "we cannot see" from "there is nothing to see".
READOUT_TABLE_ABSENT = "TABLE_ABSENT"  # Vertex never created the table => it has NEVER written a row. Diagnostic, not a verdict.
READOUT_NO_MATCH     = "NO_MATCH"      # the table exists and is queryable; our sentinel is not in it (yet).
READOUT_MATCH        = "MATCH"         # our sentinel is in it.


def mint_sentinel():
    """
    Mint a unique, greppable, PII-free sentinel to carry through a probe call.

    The sentinel is embedded in the PROMPT TEXT of a probe request, so it appears in the
    logged request payload (and typically the response), making the landed row
    ATTRIBUTABLE to this probe rather than to ambient traffic.

    Requires:
        - nothing

    Ensures:
        - returns a string matching SENTINEL_PATTERN
        - contains no user data, no project identifiers, no secrets
        - is distinct across calls with overwhelming probability
    """
    return f"{SENTINEL_PREFIX}{uuid.uuid4().hex[ :12 ]}"


def assert_sentinel_wellformed( sentinel ):
    """
    Refuse to run a probe on a sentinel that cannot be trusted to be unique.

    A short, guessable, or ambient string ("test", "hello") could MATCH A ROW SOMEBODY
    ELSE WROTE — turning an unrelated row into a false PROVEN. The instrument would then
    be lying in the SAFE-looking direction, which is the direction nobody audits.

    Requires:
        - sentinel is a string

    Ensures:
        - returns sentinel unchanged when it matches SENTINEL_PATTERN

    Raises:
        - VertexLoggingError when the sentinel is not of the minted shape
    """
    if not isinstance( sentinel, str ) or not SENTINEL_PATTERN.match( sentinel ):
        raise VertexLoggingError(
            f"Refusing to probe with sentinel {sentinel!r}: it is not a minted sentinel. "
            f"An ambient string can match a row this probe did not write, which would "
            f"report a false PROVEN. Use mint_sentinel()."
        )
    return sentinel


# ---------------------------------------------------------------------------
# §C — the region-coupling trap
# ---------------------------------------------------------------------------

def assert_bigquery_location_legal( bq_location ):
    """
    Refuse a BigQuery dataset location that cannot exist.

    "location" means THREE different things in this design (§4a-quinquies): the Vertex
    serving/config location, the BigQuery dataset location, and the Monitoring `location`
    resource label. Only the first may be `global`. BigQuery has no `global` location at
    all — so a rule comparing the two for equality is unsatisfiable BY CONSTRUCTION, and
    it broke SILENTLY the moment the Vertex SSOT moved to `global`.

    Requires:
        - bq_location is a non-empty string

    Ensures:
        - returns bq_location unchanged when it is a legal BigQuery location

    Raises:
        - VertexLoggingError when bq_location is empty or is a Vertex-only word like `global`
    """
    if not bq_location:
        raise VertexLoggingError(
            "BigQuery dataset location is empty. `bq mk` would silently default to the US "
            "multi-region — a default nobody chose is not a decision."
        )
    if bq_location in BIGQUERY_ILLEGAL_LOCATIONS:
        raise VertexLoggingError(
            f"'{bq_location}' is a VERTEX location, not a BIGQUERY location. BigQuery datasets "
            f"live in regions (us-central1) or multi-regions (US, EU). There is no `global` "
            f"dataset. A shared name is not sameness (§4e)."
        )
    return bq_location


def assert_location_pairing_certified( vertex_location, bq_location ):
    """
    Refuse a (Vertex config location, BigQuery dataset location) pair that has never been
    observed to work.

    OSQ C-5 asked which dataset location pairs with a `global`-scoped logging config. It is
    CLOSED for ("global", "US") — observed, not inferred. Every other pair is UNCERTIFIED,
    and an uncertified pair is refused rather than guessed: a guess here produces a config
    that reads back beautifully and logs nothing.

    Requires:
        - vertex_location is a non-empty string
        - bq_location is a legal BigQuery location

    Ensures:
        - returns the certification note for the pair

    Raises:
        - VertexLoggingError when the pair is not in CERTIFIED_LOCATION_PAIRINGS
    """
    assert_bigquery_location_legal( bq_location )

    pair = ( vertex_location, bq_location )
    if pair not in CERTIFIED_LOCATION_PAIRINGS:
        certified = ", ".join( f"({v} -> {b})" for v, b in sorted( CERTIFIED_LOCATION_PAIRINGS ) )
        raise VertexLoggingError(
            f"Pairing (vertex={vertex_location} -> bigquery={bq_location}) is NOT CERTIFIED. "
            f"Certified: {certified}. Certify a pairing by OBSERVING it work (write the config, "
            f"poll the LRO, land a row) — never by reasoning that it ought to."
        )
    return CERTIFIED_LOCATION_PAIRINGS[ pair ]


def assert_traffic_config_coupling( cloud_ml_region, config_location ):
    """
    Assert the ONE coupling that actually burns money: the region traffic goes to must equal
    the location the logging config was written at.

    The config is scoped to a (project, location, model) triple. Write it at one location
    and the other has NOTHING: the session runs perfectly, bills real money, and silently
    logs nothing — a false "logging is on", with every dashboard green. This is not a
    hypothetical: on 2026-07-13 the first two real Vertex calls in this project's history
    served at `global` while the design still froze the config at `us-central1`. They were
    ALREADY invisible to the config we were about to write.

    An UNCONFIGURED client lands on `global`. So this must be ASSERTED at runtime, never
    assumed from an env default (`REGION="${LUPIN_GCP_REGION:-us-central1}"` is a default,
    not a constant — a parent shell can re-arm the trap).

    Requires:
        - cloud_ml_region is a string (possibly empty — that is itself the bug)
        - config_location is a non-empty string

    Ensures:
        - returns config_location when the two agree

    Raises:
        - VertexLoggingError when they disagree, naming both values
    """
    if not cloud_ml_region:
        raise VertexLoggingError(
            "CLOUD_ML_REGION is unset. An unconfigured client lands on `global` — which may or "
            "may not be where the logging config lives. Unset is not a region; it is a coin flip."
        )
    if cloud_ml_region != config_location:
        raise VertexLoggingError(
            f"REGION-COUPLING TRAP: traffic routes to CLOUD_ML_REGION={cloud_ml_region} but the "
            f"logging config was written at location={config_location}. Requests will RUN, BILL, "
            f"and LOG NOTHING, while the config reads back enabled=true. This exact shape already "
            f"fired once on real traffic (§4a-bis)."
        )
    return config_location


# ---------------------------------------------------------------------------
# §4c — the clobber trap, disarmed BY CONSTRUCTION
# ---------------------------------------------------------------------------

def _deep_merge( base, mutation ):
    """
    Recursively overlay `mutation` onto a copy of `base`, PRESERVING every key of `base`
    that `mutation` does not mention.

    Requires:
        - base is a dict
        - mutation is a dict

    Ensures:
        - returns a new dict; neither argument is modified
        - every leaf path present in base is present in the result
    """
    merged = dict( base )
    for key, value in mutation.items():
        if isinstance( value, dict ) and isinstance( merged.get( key ), dict ):
            merged[ key ] = _deep_merge( merged[ key ], value )
        else:
            merged[ key ] = value
    return merged


def _leaf_paths( obj, prefix=() ):
    """
    Enumerate every leaf path in a nested dict, as tuples of keys.

    Requires:
        - obj is any value; dicts are recursed, everything else is a leaf

    Ensures:
        - returns a set of key-tuples, one per leaf
    """
    if not isinstance( obj, dict ) or not obj:
        return { prefix }
    paths = set()
    for key, value in obj.items():
        paths |= _leaf_paths( value, prefix + ( key, ) )
    return paths


def build_full_config_write_body( fetched_config, mutation ):
    """
    Build a COMPLETE `setPublisherModelConfig` request body by read-modify-write, so that a
    partial write is impossible BY CONSTRUCTION rather than by discipline (OSQ C-2).

    `setPublisherModelConfig` has NO `updateMask`. EVERY WRITE IS A FULL-OBJECT SET, so a
    partial write SILENTLY WIPES the rest: logging-off wipes the search gate; search-on
    wipes logging. Nothing errors. You lose a feature you believe is on.

    This trap is LIVE, not theoretical. Before 2026-07-13 there was nothing to clobber.
    THERE IS NOW: a config exists, with loggingConfig enabled at samplingRate 1 pointing at
    bq://<project>.vertex_logging. The next hand-rolled partial body destroys it.

    So this function REFUSES to build a body it was not handed a fetched object for. You
    cannot construct a write here without having read first.

    Requires:
        - fetched_config is the dict returned by fetchPublisherModelConfig (NOT None, NOT {})
        - mutation is a dict of the fields to change

    Ensures:
        - returns { "publisherModelConfig": <merged> }
        - every leaf path present in fetched_config is present in the merged object,
          including fields this codebase does not know about
        - neither argument is modified

    Raises:
        - VertexLoggingError if fetched_config is None or empty (a write with no prior read)
        - VertexLoggingError if the merge would drop any field that was present (belt to
          the read-modify-write suspenders — this should be unreachable, and it is checked
          anyway, because "should be unreachable" is how the last five defects introduced
          themselves)
    """
    if not fetched_config:
        raise VertexLoggingError(
            "Refusing to build a setPublisherModelConfig body without a prior fetch. There is no "
            "updateMask: every write is a FULL-OBJECT SET, so a body assembled from scratch "
            "SILENTLY WIPES whatever it omits. A config now EXISTS (logging enabled, samplingRate 1). "
            "Fetch it, mutate it, write the whole thing back."
        )

    merged = _deep_merge( fetched_config, mutation )

    dropped = _leaf_paths( fetched_config ) - _leaf_paths( merged )
    if dropped:
        names = ", ".join( ".".join( path ) for path in sorted( dropped ) )
        raise VertexLoggingError(
            f"Refusing to write a body that DROPS previously-present fields: {names}. "
            f"A full-object SET would erase them silently."
        )

    return { "publisherModelConfig" : merged }


# ---------------------------------------------------------------------------
# The readout — schema-agnostic, column-free, sentinel-attributable
# ---------------------------------------------------------------------------

def _refusing_query_fn( sql, params ):
    """
    The default query function: it REFUSES.

    A harness that reaches the network by DEFAULT is a harness that fires a live call the
    first time somebody imports it to look around. The live edge is opt-in, always.

    Raises:
        - VertexLoggingError, always
    """
    raise VertexLoggingError(
        "No query function was injected. This harness does not touch GCP by default — pass an "
        "explicit query_fn (see make_bq_cli_query_fn) under an authorized live run."
    )


class LoggingReadout:
    """
    Read-only view of the Vertex log sink dataset.

    Every statement it issues is a COUNT — it NEVER names a payload column (§4f), because
    `requestResponseLoggingSchemaVersion` is output-only and versioned, so the row shape is
    not knowable pre-flight and naming a column turns a schema bump into a false failure.
    Attribution is done with TO_JSON_STRING over the whole row, which is schema-agnostic.

    It never writes. The one write this harness can make (the readout positive control) is
    emitted as SQL for a caller to execute under authorization — see
    `readout_positive_control_sql()`.
    """

    def __init__( self, project_id, dataset=DEFAULT_LOG_DATASET, query_fn=None, debug=False ):
        """
        Requires:
            - project_id is a non-empty string
            - dataset is a non-empty string

        Ensures:
            - self.query_fn refuses to touch the network unless one was injected

        Raises:
            - VertexLoggingError when project_id or dataset is empty
        """
        if not project_id: raise VertexLoggingError( "project_id is required — never hardcode it; resolve it (§5a)." )
        if not dataset:    raise VertexLoggingError( "dataset is required." )

        self.project_id = project_id
        self.dataset    = dataset
        self.query_fn   = query_fn if query_fn is not None else _refusing_query_fn
        self.debug      = debug

    def list_tables( self ):
        """
        Discover the tables Vertex actually created, rather than assuming the documented name.

        The outputUri is DATASET-level (§4d), so VERTEX names the table, not us. And a
        per-publisher config could land rows in a table we never guessed — a bare
        `SELECT ... FROM request_response_logging` would miss them and report a null we would
        have believed. Discovery is not a nicety here; it is the difference between "no rows"
        and "no rows IN THE ONE TABLE I THOUGHT TO LOOK IN".

        An ABSENT table is itself a finding: Vertex creates the table on first write, so
        table-absent means it has NEVER written a row.

        Requires:
            - the injected query_fn can read INFORMATION_SCHEMA

        Ensures:
            - returns a tuple of table names present in the dataset (possibly empty)
        """
        sql  = (
            f"SELECT table_name FROM `{self.project_id}.{self.dataset}.INFORMATION_SCHEMA.TABLES` "
            f"ORDER BY table_name"
        )
        rows = self.query_fn( sql, {} )
        names = tuple( row[ "table_name" ] for row in rows )
        if self.debug: print( f"[vertex-logging] tables in {self.dataset}: {names}" )
        return names

    def count_rows( self, table ):
        """
        Count every row in a table. Names NO column (§4f).

        Requires:
            - table is a non-empty string naming a table in this dataset

        Ensures:
            - returns a non-negative integer
        """
        sql  = f"SELECT COUNT(*) AS n FROM `{self.project_id}.{self.dataset}.{table}`"
        rows = self.query_fn( sql, {} )
        return int( rows[ 0 ][ "n" ] )

    def count_sentinel( self, table, sentinel ):
        """
        Count rows ANYWHERE in which the sentinel appears — schema-agnostically.

        TO_JSON_STRING( t ) serializes the WHOLE ROW whatever its schema, so this names no
        column and survives a v1 -> v2 schema bump, while still attributing the row to THIS
        probe rather than to ambient traffic. The §4f rule and sentinel attribution were
        never in conflict.

        Requires:
            - table is a non-empty string
            - sentinel is a minted sentinel

        Ensures:
            - returns a non-negative integer
        """
        assert_sentinel_wellformed( sentinel )
        sql  = (
            f"SELECT COUNT(*) AS n FROM `{self.project_id}.{self.dataset}.{table}` AS t "
            f"WHERE STRPOS( TO_JSON_STRING( t ), @sentinel ) > 0"
        )
        rows = self.query_fn( sql, { "sentinel" : sentinel } )
        return int( rows[ 0 ][ "n" ] )

    def find_sentinel( self, sentinel, tables=None ):
        """
        Search EVERY table in the dataset for the sentinel.

        Requires:
            - sentinel is a minted sentinel
            - tables is None (discover) or an iterable of table names

        Ensures:
            - returns ( readout_state, tuple_of_tables_containing_it )
            - readout_state is READOUT_TABLE_ABSENT when the dataset has no tables at all,
              READOUT_MATCH when the sentinel is found, else READOUT_NO_MATCH
        """
        assert_sentinel_wellformed( sentinel )

        names = tuple( tables ) if tables is not None else self.list_tables()
        if not names:
            return ( READOUT_TABLE_ABSENT, () )

        hits = tuple( name for name in names if self.count_sentinel( name, sentinel ) > 0 )
        if hits:
            return ( READOUT_MATCH, hits )
        return ( READOUT_NO_MATCH, () )


def readout_positive_control_sql( project_id, dataset, sentinel ):
    """
    Emit the SQL that proves OUR READOUT IS AWAKE, independently of whether Vertex has ever
    written anything.

    This is the calibration that upgrades a null from "we cannot see ANYTHING" to "our query
    path, auth, and dataset are demonstrably working, and the VERTEX WRITE PIPELINE produced
    nothing in this window." Those are different claims, and only the second one is worth
    reporting to anybody.

    It does NOT eliminate ingest lag as an explanation — nothing can, short of a same-publisher
    positive control. It eliminates the OTHER explanations, which is the whole of what a
    positive control is for.

    This emits SQL; it does not run it. The insert is a GCP WRITE (into our own dataset, no
    model spend, ~$0) and therefore requires authorization like any other.

    Requires:
        - project_id and dataset are non-empty strings
        - sentinel is a minted sentinel

    Ensures:
        - returns ( create_and_insert_sql, verify_sql ) — the second reads the first back
          through the SAME query path the real probe uses
    """
    assert_sentinel_wellformed( sentinel )

    table  = f"`{project_id}.{dataset}.{READOUT_CANARY_TABLE}`"
    write  = (
        f"CREATE TABLE IF NOT EXISTS {table} ( sentinel STRING, written_at TIMESTAMP );\n"
        f"INSERT INTO {table} ( sentinel, written_at ) VALUES ( '{sentinel}', CURRENT_TIMESTAMP() );"
    )
    verify = (
        f"SELECT COUNT(*) AS n FROM {table} AS t "
        f"WHERE STRPOS( TO_JSON_STRING( t ), '{sentinel}' ) > 0"
    )
    return ( write, verify )


# ---------------------------------------------------------------------------
# The probe — where the canary law lives
# ---------------------------------------------------------------------------

class ProbePlan:
    """
    The declared shape of a probe, validated BEFORE any live call is fired.

    Two calls, each carrying its own sentinel:

      - the CANARY: a call we are confident IS logged (Anthropic publisher, at the location
        the config was written at). Its job is to prove the instrument is AWAKE. It is the
        positive control for the READ side.

      - the SUBJECT: the call whose logging status is the QUESTION (e.g. a Model Garden MaaS
        publisher — openai / deepseek-ai). Its silence is the finding.

    ORDERING IS EVIDENCE. The subject MUST be fired at or before the canary, so the subject's
    payload has had at least as long to be ingested as the canary's. If the LATER call lands
    and the EARLIER one does not, "it was just slow" is a materially weaker explanation than
    it would be if we had fired them the other way round. This is cheap rigor and the plan
    REFUSES to be built without it.
    """

    def __init__( self, canary_sentinel, canary_fired_at, subject_sentinel=None,
                  subject_fired_at=None, max_wait_s=1800, poll_interval_s=30 ):
        """
        Requires:
            - canary_sentinel is a minted sentinel; canary_fired_at is a monotonic timestamp
            - subject_sentinel/subject_fired_at are both given, or both omitted
            - max_wait_s > 0 and poll_interval_s > 0

        Ensures:
            - a built plan is one the canary law can render a verdict on

        Raises:
            - VertexLoggingError on a malformed sentinel, a half-specified subject, a
              non-positive bound, or a subject fired AFTER the canary
        """
        assert_sentinel_wellformed( canary_sentinel )

        if ( subject_sentinel is None ) != ( subject_fired_at is None ):
            raise VertexLoggingError(
                "A subject needs BOTH a sentinel and a fire time. Half a subject is not a probe."
            )
        if subject_sentinel is not None:
            assert_sentinel_wellformed( subject_sentinel )
            if subject_sentinel == canary_sentinel:
                raise VertexLoggingError(
                    "The canary and the subject share a sentinel. The instrument could not then "
                    "distinguish which call landed — an observation that cannot tell two worlds "
                    "apart is not an observation."
                )
            if subject_fired_at > canary_fired_at:
                raise VertexLoggingError(
                    f"The subject ({subject_fired_at}) was fired AFTER the canary ({canary_fired_at}). "
                    f"Its silence would then be explainable by ingest lag alone, and the probe could "
                    f"not have come out otherwise. Fire the SUBJECT FIRST — ordering is evidence."
                )
        if max_wait_s <= 0:      raise VertexLoggingError( "max_wait_s must be positive." )
        if poll_interval_s <= 0: raise VertexLoggingError( "poll_interval_s must be positive." )

        self.canary_sentinel  = canary_sentinel
        self.canary_fired_at  = canary_fired_at
        self.subject_sentinel = subject_sentinel
        self.subject_fired_at = subject_fired_at
        self.max_wait_s       = max_wait_s
        self.poll_interval_s  = poll_interval_s


class ProbeResult:
    """The verdict, plus everything a reader needs to distrust it."""

    def __init__( self, verdict, canary_seen_at=None, canary_tables=(), subject_tables=(),
                  readout_state=READOUT_NO_MATCH, polls=0, elapsed_s=0, residual_assumptions=() ):
        self.verdict              = verdict
        self.canary_seen_at       = canary_seen_at
        self.canary_tables        = tuple( canary_tables )
        self.subject_tables       = tuple( subject_tables )
        self.readout_state        = readout_state
        self.polls                = polls
        self.elapsed_s            = elapsed_s
        self.residual_assumptions = tuple( residual_assumptions )

    def is_admissible( self ):
        """Ensures: returns False exactly when the verdict is INADMISSIBLE."""
        return self.verdict != VERDICT_INADMISSIBLE

    def __repr__( self ):
        return (
            f"ProbeResult( verdict={self.verdict}, readout={self.readout_state}, "
            f"canary_tables={self.canary_tables}, subject_tables={self.subject_tables}, "
            f"polls={self.polls}, elapsed_s={self.elapsed_s} )"
        )


def run_probe( readout, plan, clock, sleeper=None, debug=False ):
    """
    Run the canary law to a verdict — PROVEN, REFUTED, or INADMISSIBLE. Never anything else.

    The loop, and WHY each line is the way it is:

      1. A POSITIVE NEEDS NO CANARY. If the SUBJECT is found, return PROVEN immediately —
         presence proves itself. (For the MaaS coverage question this is the ALARM branch:
         PROVEN means openai/deepseek chain-of-thought IS being persisted to BigQuery at 100%
         sampling. The caller must halt and escalate, NOT dump the row.)
      2. Poll for the CANARY. Record when it first becomes visible.
      3. NEVER a fixed sleep as a substitute for evidence: Google declares NO ingest delay for
         this pipeline (`metadata.ingestDelay: None`), so any hardcoded wait is an assumption
         wearing a constant's clothing — wrong forever, silently, the day the real delay
         changes. We poll to a BOUND and let the canary, not the clock, license the verdict.
      4. At the bound: if the canary WAS seen, the subject's silence happened inside a window
         where the instrument DEMONSTRABLY spoke => REFUTED, an admissible null.
      5. If the canary was NEVER seen: INADMISSIBLE. NOT "logging is broken." NOT a pass. The
         instrument never proved it was awake, so its silence says nothing at all.

    With no subject, this is the AC-D7 shape: does logging work? Note the asymmetry it
    inherits — the canary IS the subject there, so nothing else can calibrate the null.
    AC-D7 can therefore return PROVEN or INADMISSIBLE and NEVER REFUTED. "No rows" is NOT
    "logging is broken", and this function will not let anyone report it as such.

    Requires:
        - readout is a LoggingReadout
        - plan is a validated ProbePlan
        - clock is a zero-arg callable returning a monotonically non-decreasing number
        - sleeper is a one-arg callable (seconds) or None to not sleep between polls

    Ensures:
        - returns a ProbeResult whose verdict is one of the three admissible values
        - never returns REFUTED unless the canary was OBSERVED in this window
        - never returns REFUTED for a subject-less plan
    """
    sleeper  = sleeper if sleeper is not None else ( lambda seconds: None )
    started  = clock()
    deadline = started + plan.max_wait_s

    canary_seen_at = None
    canary_tables  = ()
    readout_state  = READOUT_NO_MATCH
    polls          = 0

    while True:
        polls += 1

        tables = readout.list_tables()

        if plan.subject_sentinel is not None:
            subject_state, subject_tables = readout.find_sentinel( plan.subject_sentinel, tables=tables )
            if subject_state == READOUT_MATCH:
                if debug: print( f"[vertex-logging] SUBJECT LANDED in {subject_tables} — positive needs no canary" )
                return ProbeResult(
                    verdict              = VERDICT_PROVEN,
                    canary_seen_at       = canary_seen_at,
                    canary_tables        = canary_tables,
                    subject_tables       = subject_tables,
                    readout_state        = READOUT_MATCH,
                    polls                = polls,
                    elapsed_s            = clock() - started,
                    residual_assumptions = (),
                )

        if canary_seen_at is None:
            canary_state, hits = readout.find_sentinel( plan.canary_sentinel, tables=tables )
            readout_state      = canary_state
            if canary_state == READOUT_MATCH:
                canary_seen_at = clock()
                canary_tables  = hits
                if debug: print( f"[vertex-logging] canary visible in {hits} after {canary_seen_at - started}s" )

                # No subject => this IS the AC-D7 question, and it is answered the moment the
                # row lands. A positive needs no canary; it IS the canary.
                if plan.subject_sentinel is None:
                    return ProbeResult(
                        verdict        = VERDICT_PROVEN,
                        canary_seen_at = canary_seen_at,
                        canary_tables  = hits,
                        readout_state  = READOUT_MATCH,
                        polls          = polls,
                        elapsed_s      = clock() - started,
                    )

        if clock() >= deadline:
            break

        sleeper( plan.poll_interval_s )

    elapsed = clock() - started

    if canary_seen_at is None:
        # The one branch this entire module exists to protect. Do NOT dress it as a result.
        return ProbeResult(
            verdict              = VERDICT_INADMISSIBLE,
            readout_state        = readout_state,
            polls                = polls,
            elapsed_s            = elapsed,
            residual_assumptions = (
                "The canary never landed, so the instrument never proved it was awake. This is "
                "NOT evidence that logging is off, and NOT evidence that the subject was unlogged. "
                "It is the absence of an instrument. Extend the bound, or fix the readout, and re-run.",
            ),
        )

    # Canary seen; subject silent, and the subject was fired FIRST (enforced at plan build).
    return ProbeResult(
        verdict              = VERDICT_REFUTED,
        canary_seen_at       = canary_seen_at,
        canary_tables        = canary_tables,
        readout_state        = READOUT_NO_MATCH,
        polls                = polls,
        elapsed_s            = elapsed,
        residual_assumptions = (
            "The canary and the subject ride the same readout (same dataset, same query path, "
            "same auth), and the canary was OBSERVED — so a readout failure is excluded.",
            "Ingest lag is assumed not to be PUBLISHER-DEPENDENT. There is no same-publisher "
            "positive control, and one cannot exist without first enabling logging for that "
            "publisher — which is the very thing under test. The subject was fired BEFORE the "
            "canary and still did not land, which weakens the lag explanation but does not kill it.",
        ),
    )


# ---------------------------------------------------------------------------
# AC-D5 precedence (F-D18) — "FAILED" and "INDETERMINATE" are not the same verdict
# ---------------------------------------------------------------------------

AC_D5_FIRED         = "FIRED"          # a web-search tool-use block was seen in the logged request/response
AC_D5_NOT_FIRED     = "NOT_FIRED"      # logging is PROVEN to work, and no such block is there. A real negative.
AC_D5_INDETERMINATE = "INDETERMINATE"  # logging is not proven, so we are BLIND. This is not a failure of search.


def classify_ac_d5( logging_verdict, search_block_found ):
    """
    Decide what a web-search observation MEANS, given what we know about the instrument it rode in on.

    AC-D5 (did web search fire?) necessarily rides the BigQuery log — legitimate, because the logged
    request/response is the ONLY place a tool-use block is visible. But that makes it DEPENDENT on
    AC-D7 (does logging work?), and the dependency is dangerous:

        If AC-D7 is not PROVEN, then AC-D5 does NOT read "search didn't fire."
        It reads "WE CANNOT SEE."

    Reporting a blind instrument as a negative result is how a team "learns" something false and rolls
    back the wrong thing. So a search-block absence is only ever a NEGATIVE when the log it was read
    from is PROVEN to be carrying rows.

    Note the asymmetry, which is the same one that governs the canary: a FOUND block is FIRED
    regardless of the logging verdict. A positive needs no calibration — if we can SEE the block, the
    log was demonstrably working for that row. Only the ABSENCE needs a proven instrument.

    Requires:
        - logging_verdict is one of VERDICT_PROVEN / VERDICT_REFUTED / VERDICT_INADMISSIBLE
        - search_block_found is a bool

    Ensures:
        - returns AC_D5_FIRED when the block was found (whatever the logging verdict)
        - returns AC_D5_NOT_FIRED ONLY when logging is PROVEN and the block is absent
        - returns AC_D5_INDETERMINATE when the block is absent and logging is not PROVEN

    Raises:
        - VertexLoggingError on a verdict this module did not produce
    """
    if logging_verdict not in ( VERDICT_PROVEN, VERDICT_REFUTED, VERDICT_INADMISSIBLE ):
        raise VertexLoggingError(
            f"Unknown logging verdict {logging_verdict!r}. AC-D5's meaning is a FUNCTION of AC-D7's "
            f"verdict — it cannot be computed from a verdict nobody rendered."
        )
    if search_block_found:                     return AC_D5_FIRED
    if logging_verdict == VERDICT_PROVEN:      return AC_D5_NOT_FIRED
    return AC_D5_INDETERMINATE


# ---------------------------------------------------------------------------
# OSQ C-4 — retry-safety is a claim about the SECOND write, so test the SECOND write
# ---------------------------------------------------------------------------

def assert_double_write_retry_safe( first_lro, second_lro, config_before, config_after ):
    """
    Judge the OSQ C-4 double-write proof: does re-applying the config succeed once the table EXISTS?

    §4d adopted a DATASET-level outputUri and called it "retry-safe by construction." That was an
    INFERENCE FROM A GAP IN THE SCHEMA: the schema documents the project-only form ("the Dataset and
    Table is created") and the full-table form ("the Dataset must exist and table must not exist"). It
    says NOTHING about the dataset-level form. Silence was read as permission — the disease this whole
    design exists to cure, committed inside one of its own fixes.

    Retry-safety is a claim about the SECOND write. So this judges the SECOND write: set once, poll the
    LRO to done with no error, then set AGAIN with the table now existing, and require the second write
    to succeed AND to leave the config unchanged. A second write that 200s while silently mangling the
    config is not retry-safety; it is the clobber trap wearing a green tick.

    Requires:
        - first_lro and second_lro are dicts as returned by the LRO poll (done / error)
        - config_before and config_after are the fetchPublisherModelConfig read-backs bracketing the
          second write

    Ensures:
        - returns True when both writes completed cleanly and the config is byte-identical across the
          second write

    Raises:
        - VertexLoggingError naming which of the four conditions failed
    """
    for label, lro in ( ( "first", first_lro ), ( "second", second_lro ) ):
        if not lro.get( "done" ):
            raise VertexLoggingError(
                f"The {label} write's LRO is NOT done. HTTP 200 means ACCEPTED, not APPLIED — an "
                f"unpolled LRO is an assumption wearing a status code (§4h)."
            )
        if lro.get( "error" ):
            raise VertexLoggingError( f"The {label} write's LRO carries an error: {lro[ 'error' ]!r}." )

    if config_before != config_after:
        raise VertexLoggingError(
            "The second write SUCCEEDED but CHANGED the config. That is not retry-safety — it is the "
            "clobber trap passing as a green tick. Diff the read-backs before trusting any re-apply."
        )
    return True


# ---------------------------------------------------------------------------
# The live-call manifest — what an authorized run would actually do, and what each proves
# ---------------------------------------------------------------------------

def describe_live_calls( project_id, vertex_location, bq_location, include_maas_probe=True ):
    """
    Enumerate every live call an authorized run would make, what it costs, and what it PROVES.

    This exists so authorization can be granted against a specific, bounded list rather than a
    vibe. Nothing in this module fires any of these; this returns data.

    Requires:
        - project_id, vertex_location, bq_location are non-empty strings

    Ensures:
        - returns a tuple of dicts, each with id / call / write / spend / proves / and, for the
          ones that answer a question, what the two possible outcomes would MEAN
    """
    assert_location_pairing_certified( vertex_location, bq_location )

    calls = [
        {
            "id"     : "L1-readout-control",
            "call"   : f"BigQuery: CREATE TABLE IF NOT EXISTS + INSERT one row into "
                       f"{project_id}.{DEFAULT_LOG_DATASET}.{READOUT_CANARY_TABLE}, then SELECT it back",
            "write"  : "YES — BigQuery only, into our own dataset. No Vertex config touched. No model invoked.",
            "spend"  : "~$0 (one row; on-demand query bytes are negligible)",
            "proves" : "The READOUT is awake: auth, dataset, and query path demonstrably work. Upgrades a "
                       "later null from 'we cannot see anything' to 'the Vertex write pipeline produced nothing'.",
        },
        {
            "id"     : "L2-canary-anthropic",
            "call"   : f"Vertex rawPredict: claude-opus-4-8 @ locations/{vertex_location}, 1-token prompt "
                       f"carrying a minted sentinel",
            "write"  : "NO config write. One model invocation.",
            "spend"  : "~$0.01 (a few tokens of Opus)",
            "proves" : "AC-D7: that DATA ARRIVES in BigQuery — not merely that the config reads back. Row "
                       "found => PROVEN. Row not found within the bound => INADMISSIBLE, never 'broken'.",
        },
    ]

    if include_maas_probe:
        calls.insert( 1, {
            "id"      : "L0-subject-maas",
            "call"    : "Vertex rawPredict: openai/gpt-oss-120b-maas (Model Garden MaaS), 1-token prompt "
                        "carrying a DIFFERENT minted sentinel. FIRED FIRST — before L2 — because ordering is evidence.",
            "write"   : "NO config write. One model invocation.",
            "spend"   : "~$0.001",
            "proves"  : "OSQ 823be9cc: does the logging config cover the Model Garden MaaS publishers, or only "
                        "the Anthropic one?",
            "if_yes"  : "🔴 The MaaS sentinel lands => raw CHAIN-OF-THOUGHT (gpt-oss streams a reasoning_content "
                        "channel) is being persisted to BigQuery at 100% sampling. A privacy edge Rick has NOT "
                        "approved. HALT and escalate — do not dump the row.",
            # THE CONCLUSION. It is deliberately MECHANISM-FREE — see if_no_mechanism, and the invariant
            # test that holds this field to it. A null answers the privacy question and NOTHING ELSE.
            "if_no"   : "The MaaS sentinel is silent while the Anthropic canary — fired LATER — lands. That is an "
                        "ADMISSIBLE null, and it answers exactly ONE question: the PRIVACY question (823be9cc). "
                        "gpt-oss chain-of-thought is NOT being persisted to BigQuery by this config. That is the "
                        "conclusion, and it is the WHOLE conclusion.",

            # WHY it is silent is a DIFFERENT question, and this probe cannot answer it. Keep it open.
            "if_no_mechanism" : "OPEN — AND IT MUST STAY OPEN. The null CANNOT SELECT between the two worlds that "
                        "would both produce it: PUBLISHER-SCOPE (the config's resource path is "
                        "publishers/anthropic/models/{model}, so a publisher named `openai` may simply not be in "
                        "scope) and LOCATION-SCOPE (the config is scoped to `global`, and the traffic's true serving "
                        "region is UNKNOWN). ONE OBSERVATION, TWO WORLDS. The location leg cannot even be tested "
                        "from here: bug 13c3c480 — the MaaS openapi/chat/completions endpoint IGNORES its "
                        "locations/{region} path segment, returning byte-identical 200s for `global`, for "
                        "`us-central1`, and for the FICTIONAL `narnia-1`. An axis that CANNOT COME OUT OTHERWISE is "
                        "not an oracle. So: REPORT THE PRIVACY ANSWER; NAME NO MECHANISM. Naming one here would be "
                        "reasoning past a limitation stated one field earlier — and A CONFESSION IS NOT A "
                        "CORRECTION. (This field exists because the first draft DID name one: it concluded 'the "
                        "config does not cover that publisher', which is a publisher-scope verdict the null never "
                        "earned. Caught by Rio on cold review, 2026-07-14. The defect was inside the FIX for "
                        "13c3c480 — rigor fails where relief lives.)",
        } )

    return tuple( calls )


class _FakeReadout:
    """
    A readout whose row lands only after `lands_on_poll` polls — i.e. it LAGS, like the real
    one. Used by the smoke test to prove the harness survives the lag that makes a bare SELECT
    a liar.
    """

    def __init__( self, lands_on_poll ):
        self.lands_on_poll = lands_on_poll
        self.polls         = 0

    def list_tables( self ):
        """Ensures: returns the documented default table, always."""
        return ( DOCUMENTED_DEFAULT_TABLE, )

    def find_sentinel( self, sentinel, tables=None ):
        """Ensures: returns a MATCH only once `lands_on_poll` polls have elapsed."""
        self.polls += 1
        if self.polls >= self.lands_on_poll: return ( READOUT_MATCH, ( DOCUMENTED_DEFAULT_TABLE, ) )
        return ( READOUT_NO_MATCH, () )


def _expect_raises( exception_type, fn, *args, **kwargs ):
    """
    Assert that `fn` fails loud with `exception_type`.

    A guard that is never seen to FIRE is not a proven guard. The smoke test uses this so that
    "the trap is disarmed" is an observation, not a claim.

    Requires:
        - exception_type is an exception class; fn is callable

    Ensures:
        - returns the raised exception when fn raises exception_type

    Raises:
        - AssertionError when fn does NOT raise — a guard that stayed silent is a FAILURE
    """
    try:
        fn( *args, **kwargs )
    except exception_type as raised:
        return raised
    raise AssertionError( f"{fn.__name__} did NOT raise {exception_type.__name__} — the guard is asleep." )


def quick_smoke_test():
    """Exercise the canary law end-to-end against a fake readout. No network. No spend."""
    import cosa.utils.util as du

    du.print_banner( "vertex_logging quick smoke test", prepend_nl=True )

    ticks = [ 0 ]
    def clock():
        ticks[ 0 ] += 30
        return ticks[ 0 ]

    plan   = ProbePlan( mint_sentinel(), canary_fired_at=0, max_wait_s=300, poll_interval_s=30 )
    result = run_probe( _FakeReadout( lands_on_poll=2 ), plan, clock=clock )
    assert result.verdict == VERDICT_PROVEN, result
    print( f"✓ canary lands LATE   -> {result.verdict}       (the ingest lag did NOT become a false negative)" )

    ticks[ 0 ] = 0
    plan   = ProbePlan( mint_sentinel(), canary_fired_at=0, max_wait_s=120, poll_interval_s=30 )
    result = run_probe( _FakeReadout( lands_on_poll=999 ), plan, clock=clock )
    assert result.verdict == VERDICT_INADMISSIBLE, result
    print( f"✓ canary NEVER lands  -> {result.verdict} (NOT 'logging is broken' — the instrument never spoke)" )

    _expect_raises( VertexLoggingError, build_full_config_write_body, None, { "loggingConfig" : { "enabled" : False } } )
    print( "✓ clobber trap        -> a write body CANNOT be built without a prior fetch" )

    _expect_raises( VertexLoggingError, assert_traffic_config_coupling, "us-central1", "global" )
    print( "✓ region-coupling     -> traffic/config location mismatch fails loud" )

    _expect_raises( VertexLoggingError, assert_bigquery_location_legal, "global" )
    print( "✓ location namespaces -> `global` is refused as a BigQuery dataset location" )

    du.print_banner( "vertex_logging smoke test PASSED", prepend_nl=True )


if __name__ == "__main__":
    quick_smoke_test()
