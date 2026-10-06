"""
Vertex request-response logging verification harness.

Design: src/rnd/v0.1.9/2026.07.13-vertex-model-garden-toggle-search-and-logging.md

`setPublisherModelConfig` has been written and read back, so we know the config reads back.
We do not know that data arrives. Those are different claims. This module exists to prove the
second one, or to refuse to render a verdict at all.

The law: BigQuery ingest lags, so a "not found" is not evidence of "not logged". It may merely be
early. A null is not evidence until the instrument is proven. A null that confirms a suspicion also
sails through a checkpoint that a contradicting one never would. So no function here returns
"not logged" from a bare `SELECT`.
Every negative verdict is gated on a canary having been seen in the same window in which the
silence is trusted. A canary is a known-good write carrying a unique greppable sentinel.
If the canary does not land, the verdict is `INADMISSIBLE`, never `REFUTED`.
An observation is evidence only if it could have come out otherwise.

A positive needs no canary. Presence proves itself, and only absence needs a calibrated instrument.

The sentinel search is schema-agnostic. `requestResponseLoggingSchemaVersion` is output-only and
versioned (v1/v2), so the row shape is not knowable pre-flight. Naming a column would turn a schema
bump into a false failure, so assertions use row counts and never a column.
`TO_JSON_STRING(t)` serializes the whole row whatever its schema. The query below names no column
and still finds our own row, not somebody else's traffic:

    `SELECT COUNT(*) FROM p.d.t AS t WHERE STRPOS( TO_JSON_STRING( t ), @sentinel ) > 0`

Residual limit: if the payload lands bytes-encoded or compressed, `TO_JSON_STRING` base64-encodes
it and the sentinel will not match. That yields `INADMISSIBLE` (canary unseen), not a false
`REFUTED`, so the instrument fails safe.

Nothing here reaches the network. Every outbound edge is an injected callable (`query_fn`, `clock`,
`sleeper`), and the default query function refuses. A live run is composed by the caller under
explicit authorization. The live calls it needs are listed by `describe_live_calls()`.
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

    The sentinel is embedded in the prompt text of a probe request, so it appears in the logged request payload (and typically the response).
    That makes the landed row attributable to this probe rather than to ambient traffic.

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

    A short, guessable or ambient string ("test", "hello") could match a row somebody else wrote and turn it into a false `PROVEN`.
    The instrument would then lie in the safe-looking direction, which nobody audits.

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

    "Location" means three different things here: the Vertex serving/config location, the BigQuery dataset location, and the Monitoring `location` resource label. Only the first may be `global`.
    BigQuery has no `global` location. A rule comparing the two for equality can never be satisfied,
    and it broke silently once the Vertex location became `global`.

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
    Refuse a (Vertex config location, BigQuery dataset location) pair never observed to work.

    Only ("global", "US") is certified, and it was observed, not inferred. An uncertified pair is refused rather than guessed,
    because a guess produces a config that reads back correctly and logs nothing.

    Requires:
        - vertex_location is a non-empty string
        - bq_location is a legal BigQuery location

    Ensures:
        - returns the certification note for the pair

    Raises:
        - VertexLoggingError when the pair is not in CERTIFIED_LOCATION_PAIRINGS
        - VertexLoggingError when bq_location is not a legal BigQuery location
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
    Assert that the traffic region equals the location the logging config was written at.

    The config is scoped to a (project, location, model) triple. Written at one location, the other has nothing.
    The session then runs, bills real money and logs nothing, while the config reads back as on. This has happened on real traffic.
    An unconfigured client lands on `global`, so assert the coupling at run time, never from an env default, which a parent shell can change.

    Requires:
        - cloud_ml_region is a string (possibly empty; an empty value is itself the bug)
        - config_location is a non-empty string

    Ensures:
        - returns config_location when the two agree

    Raises:
        - VertexLoggingError when they disagree, naming both values
        - VertexLoggingError when cloud_ml_region is empty
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
    Recursively overlay `mutation` onto a copy of `base`, keeping unmentioned `base` keys.

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
    Build a complete `setPublisherModelConfig` request body by read-modify-write.

    The API has no `updateMask`, so every write is a full-object set, and a partial write silently wipes the rest. Logging-off wipes the search gate, and search-on wipes logging. Nothing errors.
    A config now exists (logging enabled, sampling rate 1, pointing at the log dataset), so the next hand-rolled partial body would destroy it.
    This function refuses to build a body without a fetched object, so a partial write is structurally impossible, not a matter of discipline.

    Requires:
        - fetched_config is the dict returned by fetchPublisherModelConfig (not None, not {})
        - mutation is a dict of the fields to change

    Ensures:
        - returns { "publisherModelConfig": <merged> }
        - every leaf path present in fetched_config is present in the merged object,
          including fields this codebase does not know about
        - neither argument is modified

    Raises:
        - VertexLoggingError if fetched_config is None or empty (a write with no prior read)
        - VertexLoggingError if the merge would drop any field that was present; this check should
          be unreachable and is kept anyway, as a second guard behind the read-modify-write
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
    The default query function: it refuses.

    A harness that reaches the network by default fires a live call the first time somebody imports it to look around. The live edge is always opt-in.

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

    Every statement it issues is a `COUNT`, and it never names a payload column.
    The row shape is not knowable pre-flight, because `requestResponseLoggingSchemaVersion` is output-only and versioned.
    Naming a column would turn a schema bump into a false failure.
    Attribution uses `TO_JSON_STRING` over the whole row, which is schema-agnostic.
    It never writes. The one write this harness can make, the readout positive control, is emitted as SQL for a caller to run under authorization (see `readout_positive_control_sql()`).
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
        Discover the tables Vertex created, rather than assuming the documented name.

        The outputUri is dataset-level, so Vertex names the table, not us. A per-publisher config could land rows in a table we never guessed. A bare `SELECT ... FROM request_response_logging` would miss them and report a null we would have believed.
        Discovery separates "no rows" from "no rows in the one table I thought to look in". An absent table is itself a finding: Vertex creates the table on first write, so an absent table means it has never written a row.

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
        Count every row in a table, naming no column.

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
        Count the rows in which the sentinel appears anywhere, without naming a column.

        `TO_JSON_STRING( t )` serializes the whole row whatever its schema.
        So this survives a v1 to v2 schema bump and still attributes the row to this probe, not to ambient traffic.

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
        Search every table in the dataset for the sentinel.

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
    Emit the SQL that proves our readout is awake, whether or not Vertex has written anything.

    This upgrades a null from "we cannot see anything" to "our readout works and Vertex wrote nothing in this window". Only the second claim is worth reporting.
    It does not rule out ingest lag, which nothing can short of a same-publisher positive control. It rules out the other explanations.
    It emits SQL and does not run it. The insert is a GCP write into our own dataset (no model spend, about $0), so it needs authorization.

    Requires:
        - project_id and dataset are non-empty strings
        - sentinel is a minted sentinel

    Ensures:
        - returns ( create_and_insert_sql, verify_sql ); the second reads the first back
          through the same query path the real probe uses
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
    The declared shape of a probe, validated before any live call is fired.

    Two calls, each carrying its own sentinel. The canary is a call we are confident is logged (Anthropic publisher, at the location the config was written at). It proves the instrument is awake and is the positive control for the read side.
    The subject is the call whose logging status is the question, for example a Model Garden MaaS publisher such as openai or deepseek-ai. Its silence is the finding.
    Ordering is evidence. The subject must be fired at or before the canary, so its payload has had at least as long to be ingested. If the later call lands and the earlier one does not, "it was just slow" is a weaker explanation. The plan refuses to be built without this.
    """

    def __init__( self, canary_sentinel, canary_fired_at, subject_sentinel=None,
                  subject_fired_at=None, max_wait_s=1800, poll_interval_s=30 ):
        """
        Validate and store the sentinels, fire times and polling bounds of a probe.

        Requires:
            - canary_sentinel is a minted sentinel; canary_fired_at is a monotonic timestamp
            - subject_sentinel/subject_fired_at are both given, or both omitted
            - max_wait_s > 0 and poll_interval_s > 0

        Ensures:
            - a built plan is one the canary law can render a verdict on

        Raises:
            - VertexLoggingError on a malformed sentinel, a half-specified subject, a
              non-positive bound, a subject that shares the canary's sentinel, or a subject
              fired after the canary
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
    """
    The verdict, plus everything a reader needs to distrust it.
    """

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
        """
        Say whether the verdict is admissible, that is, anything but VERDICT_INADMISSIBLE.

        Ensures:
            - returns False exactly when the verdict is VERDICT_INADMISSIBLE
        """
        return self.verdict != VERDICT_INADMISSIBLE

    def __repr__( self ):
        return (
            f"ProbeResult( verdict={self.verdict}, readout={self.readout_state}, "
            f"canary_tables={self.canary_tables}, subject_tables={self.subject_tables}, "
            f"polls={self.polls}, elapsed_s={self.elapsed_s} )"
        )


def run_probe( readout, plan, clock, sleeper=None, debug=False ):
    """
    Run the canary law to a verdict: proven, refuted or inadmissible, and never anything else.

    It polls to a bound and lets the canary, not the clock, license the verdict. Google declares no ingest delay (`metadata.ingestDelay: None`), so a hardcoded sleep would go silently wrong when it changes.
    With no subject the canary is the subject, so the null cannot be calibrated and the result is never VERDICT_REFUTED. "No rows" is not "logging is broken".

    Requires:
        - readout is a LoggingReadout
        - plan is a validated ProbePlan
        - clock is a zero-arg callable returning a monotonically non-decreasing number
        - sleeper is a one-arg callable (seconds) or None to not sleep between polls

    Ensures:
        - returns a ProbeResult whose verdict is one of the three verdict values
        - a found subject returns VERDICT_PROVEN at once, because presence proves itself and needs no canary;
          for the Model Garden MaaS coverage question this is the alarm branch, meaning
          chain-of-thought is persisted to BigQuery at 100% sampling, and the caller must halt
          and escalate rather than dump the row
        - a canary seen but a subject silent at the bound returns VERDICT_REFUTED, an admissible null,
          because the silence fell inside a window where the instrument demonstrably spoke
        - a canary never seen returns VERDICT_INADMISSIBLE, which is neither "logging is broken" nor a pass,
          because an instrument that never proved it was awake says nothing
        - never returns VERDICT_REFUTED unless the canary was observed in this window
        - never returns VERDICT_REFUTED for a subject-less plan
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
    Decide what a web-search observation means, given whether logging is proven.

    The question is whether web search fired. It rides the BigQuery log, the only place a tool-use block is visible, so it depends on whether logging works. If logging is not proven, an absent block reads "we cannot see", not "search did not fire".
    Reporting a blind instrument as a negative is how a team learns something false and rolls back the wrong thing.
    A found block is `FIRED` whatever the logging verdict: a positive needs no calibration, and only absence needs a proven instrument.

    Requires:
        - logging_verdict is one of VERDICT_PROVEN / VERDICT_REFUTED / VERDICT_INADMISSIBLE
        - search_block_found is a bool

    Ensures:
        - returns AC_D5_FIRED when the block was found (whatever the logging verdict)
        - returns AC_D5_NOT_FIRED only when logging is VERDICT_PROVEN and the block is absent
        - returns AC_D5_INDETERMINATE when the block is absent and logging is not VERDICT_PROVEN

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
    Judge the double-write proof: re-applying the config must succeed and change nothing.

    The schema documents two outputUri forms. The project-only form says "the Dataset and Table is created"; the full-table form says "the Dataset must exist and table must not exist". It is silent on the dataset-level form, so retry-safety cannot be read from the docs. The second write, with the table now existing, is the open question.
    Retry-safety is a claim about the second write. Set once, poll the LRO to done with no error, then set again with the table now existing.
    The second write must succeed and leave the config unchanged. One that returns 200 while mangling the config is the clobber trap with a green tick.

    Requires:
        - first_lro and second_lro are dicts as returned by the LRO poll (done / error)
        - config_before and config_after are the fetchPublisherModelConfig read-backs bracketing the
          second write

    Ensures:
        - returns True when both writes completed cleanly and the config is equal across the
          second write

    Raises:
        - VertexLoggingError naming which condition failed: a write whose LRO is not done or carries
          an error, or a config that changed across the second write
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
    Enumerate every live call an authorized run would make, what it costs, and what it proves.

    This lets authorization be granted against a specific, bounded list. Nothing in this module fires any of these calls; this returns data.

    Requires:
        - project_id, vertex_location, bq_location are non-empty strings

    Ensures:
        - returns a tuple of dicts, each with id / call / write / spend / proves; the MaaS subject
          entry also carries if_yes, if_no and if_no_mechanism, saying what each outcome would mean

    Raises:
        - VertexLoggingError when the (vertex_location, bq_location) pair is not certified
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
    A readout whose row lands only after `lands_on_poll` polls, so it lags like the real one.

    The smoke test uses it to prove the harness survives the lag that makes a bare `SELECT` a liar.
    """

    def __init__( self, lands_on_poll ):
        self.lands_on_poll = lands_on_poll
        self.polls         = 0

    def list_tables( self ):
        """
        Return the documented default table, whatever the caller asks.

        Ensures:
            - returns the documented default table, always
        """
        return ( DOCUMENTED_DEFAULT_TABLE, )

    def find_sentinel( self, sentinel, tables=None ):
        """
        Return READOUT_MATCH only after `lands_on_poll` polls have elapsed.

        Ensures:
            - returns READOUT_MATCH only once `lands_on_poll` polls have elapsed
        """
        self.polls += 1
        if self.polls >= self.lands_on_poll: return ( READOUT_MATCH, ( DOCUMENTED_DEFAULT_TABLE, ) )
        return ( READOUT_NO_MATCH, () )


def _expect_raises( exception_type, fn, *args, **kwargs ):
    """
    Assert that `fn` fails loud with `exception_type`.

    A guard never seen to fire is not a proven guard. The smoke test uses this so that "the guard works" is an observation, not a claim.

    Requires:
        - exception_type is an exception class; fn is callable

    Ensures:
        - returns the raised exception when fn raises exception_type

    Raises:
        - AssertionError when fn does not raise; a guard that stayed silent is a failure
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
