"""
Unit tests for the Lane-2 E2E harness's OBSERVABILITY — row 1cd30181.

WHAT IS UNDER TEST HERE IS THE INSTRUMENT, NOT THE PRODUCT. No podcast is
generated, no server is contacted, no audio is rendered. Every test drives the
harness's real decision functions with a controlled clock and scripted queue
answers, and asserts on what the harness CONCLUDES.

THE DEFECT (row 1cd30181, found by Rachel 2026-08-04, reproduced at HEAD
2026-08-17): the harness polled for 720s and printed a two-state table. The
podcast chain contains a script-review gate that is redirected away from the
test user by operator routing (`voice gate service accounts` in lupin-app.ini
includes the harness's own login), so the job only advances when that gate fails
open after 600s — and a measured run landed at 733.2s, about 13 seconds past the
cutoff. The harness stopped watching, wrote FAIL, and read as a broken product.
Stage 3 false-failed independently: its `docker logs --since 10m` window was
evaluated AFTER the poll loop, so the "Initialized for" line written at push time
had already aged out of the window on any run longer than ten minutes.

THE FIX, AND WHY WIDENING THE TIMEOUT IS NOT IT. A bigger number alone converts a
false FAIL into a false PASS on the next slow run. The fix is that a stage the
harness never observed is INCONCLUSIVE — earned neither green nor red. The tests
below therefore care as much about what the harness REFUSES to conclude as about
what it concludes, and every "it can report red" case has a matching control
showing red is still reachable. A guard that rejects everything passes every
red test.
"""

import importlib.util
import os

import pytest


# ── Load the date-named harness by path (not a legal module name) ────────────
_LUPIN_ROOT   = os.environ.get( "LUPIN_ROOT", "/mnt/DATA01/include/www.deepily.ai/projects/lupin" )
_HARNESS_PATH = os.path.join(
    _LUPIN_ROOT, "src", "rnd", "v0.2.0", "2026.08.04-lane2-e2e-tiffany-harness.py"
)


def _load():
    spec = importlib.util.spec_from_file_location( "lane2_harness_under_test", _HARNESS_PATH )
    mod  = importlib.util.module_from_spec( spec )
    spec.loader.exec_module( mod )
    return mod


pytestmark = pytest.mark.skipif(
    not os.path.exists( _HARNESS_PATH ), reason=f"harness not found at {_HARNESS_PATH}"
)


@pytest.fixture
def h():
    return _load()


# ── Test doubles ────────────────────────────────────────────────────────────
class FakeClock:
    """A monotonic clock the test advances by hand, so a 20-minute timeout is
    exercised in microseconds and the result is deterministic."""

    def __init__( self ):
        self.t = 1000.0

    def monotonic( self ):
        return self.t

    def sleep( self, n ):
        self.t += n

    def strftime( self, fmt ):
        return "00:00:00"

    def time( self ):
        return self.t


class FakeWs:
    def __init__( self, job_id="pg-deadbeef", alive=True, authed=True, error=None ):
        self.job_id   = job_id
        self.answered = []
        self.authed   = authed
        self.error    = error
        self._alive   = alive

    def start( self ):  pass
    def stop( self ):   pass
    def is_alive( self ): return self._alive


class FakeResp:
    def __init__( self, status=200, payload=None, text="" ):
        self.status_code = status
        self._payload    = payload if payload is not None else {}
        self.text        = text

    def json( self ):
        return self._payload

    def raise_for_status( self ):
        if self.status_code >= 400:
            raise RuntimeError( f"HTTP {self.status_code}" )


def _wire( h, monkeypatch, *, find_job, doc_stage, content, ws=None, clock=None ):
    """Install doubles for everything main() touches except the logic under test."""
    clock = clock or FakeClock()
    monkeypatch.setattr( h, "time", clock )
    monkeypatch.setattr( h, "login", lambda: ( "t@example.com", "jwt", { "Authorization": "Bearer jwt" } ) )
    monkeypatch.setattr( h, "write_seed", lambda: None )
    monkeypatch.setattr( h, "remove_seed", lambda: None )
    monkeypatch.setattr( h, "WsAutoAnswer", lambda *a, **k: ( ws or FakeWs() ) )
    monkeypatch.setattr( h, "find_job", find_job )
    monkeypatch.setattr( h, "doc_resolved_from_logs", lambda **kw: doc_stage )
    monkeypatch.setattr( h, "verify_content", lambda *a, **k: content )
    monkeypatch.setattr(
        h.requests, "post",
        lambda url, **kw: FakeResp( 200, { "job_id": None, "result": "ok", "display_name": "Podcast" } ),
    )
    return clock


def _never_terminal( headers, queue, job_id ):
    """The job is alive and running, and never reaches a terminal queue while we watch."""
    return { "job_id": job_id } if queue == "run" else None


# ── 1. THE REGRESSION ITSELF ────────────────────────────────────────────────
def test_job_still_running_at_cutoff_is_inconclusive_never_fail( h, monkeypatch ):
    """
    The exact shape of row 1cd30181: the harness runs out of patience while the
    job is still legitimately in flight (the script gate has not failed open yet).

    It must NOT report FAIL — it never observed anything go wrong — and it must
    NOT report PASS. Exit code 2 says "I could not tell".
    """
    _wire( h, monkeypatch, find_job=_never_terminal, doc_stage=h.PASS, content=h.PASS )

    rc = h.main( [ "--no-seed", "--no-mode" ] )

    assert rc == 2, "a run that outlasted the harness's patience must exit 2 (inconclusive)"


def test_stage_table_marks_unobserved_stages_inconclusive_not_failed( h, monkeypatch, capsys ):
    """The printed table must not contain the word FAIL for stages never observed."""
    _wire( h, monkeypatch, find_job=_never_terminal, doc_stage=h.PASS, content=h.PASS )

    h.main( [ "--no-seed", "--no-mode" ] )
    out = capsys.readouterr().out

    assert "INCONCLUSIVE  5_job_done"   in out.replace( "INCONCLUSIVE ", "INCONCLUSIVE " ) or \
           "INCONCLUSIVE" in out, "5_job_done must be reported INCONCLUSIVE"
    stage_lines = [ l for l in out.splitlines() if "5_job_done" in l or "6_content_ok" in l ]
    assert stage_lines, "stage table did not print the completion stages"
    for line in stage_lines:
        assert "FAIL" not in line, f"unobserved stage wrongly reported as FAIL: {line!r}"
    assert "NOT the product failing" in out, "the log must say plainly that this is not a product defect"


def test_completion_just_past_the_old_720s_cutoff_now_passes( h, monkeypatch ):
    """
    A job that finishes at ~733s — the measured duration of run pg-6c221006 — is
    inside the new window and outside the old one. This is the run the harness
    used to call broken.
    """
    clock = FakeClock()
    t0    = clock.t

    def finishes_at_733s( headers, queue, job_id ):
        if clock.t - t0 >= 733:
            return { "job_id": job_id, "artifacts": {} } if queue == "done" else None
        return { "job_id": job_id } if queue == "run" else None

    _wire( h, monkeypatch, find_job=finishes_at_733s, doc_stage=h.PASS, content=h.PASS, clock=clock )

    assert h.main( [ "--no-seed", "--no-mode" ] ) == 0
    assert h.TIMEOUT_S > 733, "the default window must cover a gate-fail-open run"


def test_fast_job_never_caught_mid_flight_is_not_a_false_inconclusive( h, monkeypatch ):
    """
    A job that reaches done between two polls was never seen in the run queue. Left
    INCONCLUSIVE that would exit 2 on a run where the product did everything right.
    Reaching done proves it ran.
    """
    def straight_to_done( headers, queue, job_id ):
        return { "job_id": job_id, "artifacts": {} } if queue == "done" else None

    _wire( h, monkeypatch, find_job=straight_to_done, doc_stage=h.PASS, content=h.PASS )

    assert h.main( [ "--no-seed", "--no-mode" ] ) == 0


# ── 2. THE CONTROLS — red must still be reachable ───────────────────────────
def test_dead_job_still_earns_a_real_fail( h, monkeypatch ):
    """
    THE CONTROL for every test above. If the fix made FAIL unreachable it would
    pass every "no false red" test while being worthless. A job that genuinely
    died must still exit 1.
    """
    def dies( headers, queue, job_id ):
        return { "job_id": job_id, "error": "orchestrator exploded" } if queue == "dead" else None

    _wire( h, monkeypatch, find_job=dies, doc_stage=h.PASS, content=h.PASS )

    assert h.main( [ "--no-seed", "--no-mode" ] ) == 1, "a dead job is an observed negative and must exit 1"


def test_transient_rate_limit_is_inconclusive_not_a_product_fail( h, monkeypatch ):
    """An upstream rate limit is not the chain being broken."""
    def rate_limited( headers, queue, job_id ):
        return { "job_id": job_id, "error": "Please try again in a few minutes" } if queue == "dead" else None

    _wire( h, monkeypatch, find_job=rate_limited, doc_stage=h.PASS, content=h.PASS )

    assert h.main( [ "--no-seed", "--no-mode" ] ) == 2


def test_routing_miss_earns_a_fail( h, monkeypatch ):
    """An rp- job means the router picked the wrong product — an observed negative."""
    _wire( h, monkeypatch, find_job=lambda *a: None, doc_stage=h.PASS, content=h.PASS,
           ws=FakeWs( job_id="rp-12345678" ) )

    assert h.main( [ "--no-seed", "--no-mode" ] ) == 1


# ── 3. THE OBSERVER WATCHING ITSELF ─────────────────────────────────────────
def test_dead_auto_answer_socket_does_not_convict_the_product( h, monkeypatch ):
    """
    If the auto-answer listener dies, every later ask goes unanswered and the job
    stalls. That stall is the harness's fault. It must be reported as such.
    """
    _wire( h, monkeypatch, find_job=_never_terminal, doc_stage=h.FAIL, content=h.PASS,
           ws=FakeWs( alive=False, authed=True, error="ConnectionClosed()" ) )

    rc = h.main( [ "--no-seed", "--no-mode" ] )
    assert rc == 2, "a dead observer cannot produce a product verdict"


def test_degraded_observer_downgrades_a_red_it_cannot_trust( h, monkeypatch, capsys ):
    """A red produced while the observer was broken is downgraded, and says so."""
    _wire( h, monkeypatch, find_job=_never_terminal, doc_stage=h.FAIL, content=h.PASS,
           ws=FakeWs( authed=False ) )

    h.main( [ "--no-seed", "--no-mode" ] )
    out = capsys.readouterr().out
    assert "downgrading" in out and "OBSERVER DEGRADED" in out


def test_unreadable_queue_api_is_not_evidence_the_job_never_finished( h, monkeypatch ):
    """A queue endpoint returning 500 for the whole run must not read as 'not done'."""
    _wire( h, monkeypatch, find_job=lambda *a: h.UNOBSERVED, doc_stage=h.PASS, content=h.PASS )

    assert h.main( [ "--no-seed", "--no-mode" ] ) == 2


# ── 4. find_job's three answers ─────────────────────────────────────────────
def test_find_job_distinguishes_absent_from_unaskable( h, monkeypatch ):
    """None means 'the server says no'. UNOBSERVED means 'the server did not say'."""
    monkeypatch.setattr( h.requests, "get",
                         lambda url, **kw: FakeResp( 200, { "done_jobs_metadata": [] } ) )
    assert h.find_job( {}, "done", "pg-1" ) is None, "an empty answer is a real negative"

    monkeypatch.setattr( h.requests, "get", lambda url, **kw: FakeResp( 500 ) )
    assert h.find_job( {}, "done", "pg-1" ) is h.UNOBSERVED, "a 500 is not an answer about the job"

    def boom( url, **kw ):
        raise ConnectionError( "refused" )
    monkeypatch.setattr( h.requests, "get", boom )
    assert h.find_job( {}, "done", "pg-1" ) is h.UNOBSERVED, "a connection error is not an answer"

    monkeypatch.setattr( h.requests, "get",
                         lambda url, **kw: FakeResp( 200, { "done_jobs_metadata": [ { "job_id": "pg-1" } ] } ) )
    assert h.find_job( {}, "done", "pg-1" ) == { "job_id": "pg-1" }, "the positive control must still match"


# ── 5. Stage 3's log window ─────────────────────────────────────────────────
def test_stage3_window_covers_the_whole_run_not_a_fixed_ten_minutes( h, monkeypatch ):
    """
    The original bug: `--since 10m` evaluated after a ~12-minute run excluded the
    push-time line it was looking for. The window must now scale with run age.
    """
    seen = {}

    class Done:
        returncode = 0
        stdout     = f"[PodcastOrchestratorAgent] Initialized for: /var/lupin/io/x/{h.SEED_FILENAME}\n"
        stderr     = ""

    def fake_run( argv, **kw ):
        seen[ "argv" ] = argv
        return Done()

    clock = FakeClock()
    monkeypatch.setattr( h, "time", clock )
    monkeypatch.setattr( "subprocess.run", fake_run )

    start = clock.t
    clock.t += 900                                  # a 15-minute run
    assert h.doc_resolved_from_logs( run_started_monotonic=start ) == h.PASS

    since = seen[ "argv" ][ seen[ "argv" ].index( "--since" ) + 1 ]
    assert since.endswith( "s" )
    window = int( since[ :-1 ] )
    assert window >= 900, (
        f"window {window}s is shorter than the {900}s run — the push-time line would age out, "
        f"which is exactly the original defect"
    )
    assert window != 600, "the fixed 10-minute window must be gone"


def test_stage3_unreadable_log_is_inconclusive_but_a_readable_one_still_fails( h, monkeypatch ):
    """Both directions: an unreadable log cannot convict; a readable one still can."""
    class Broken:
        returncode = 1
        stdout     = ""
        stderr     = "no such container"

    monkeypatch.setattr( "subprocess.run", lambda *a, **k: Broken() )
    assert h.doc_resolved_from_logs( run_started_monotonic=None ) == h.INCONCLUSIVE

    class EmptyButReadable:
        returncode = 0
        stdout     = "some unrelated log line\n"
        stderr     = ""

    monkeypatch.setattr( "subprocess.run", lambda *a, **k: EmptyButReadable() )
    assert h.doc_resolved_from_logs( run_started_monotonic=None ) == h.FAIL, (
        "a log that WAS read and lacks the line is a real negative — red must stay reachable"
    )


# ── 6. Content verification ─────────────────────────────────────────────────
def test_content_check_three_states( h, monkeypatch ):
    monkeypatch.setattr( h.requests, "get", lambda *a, **k: FakeResp( 404 ) )

    assert h.verify_content( {}, { "completion_abstract": "" } ) == h.INCONCLUSIVE, (
        "no fetchable text is an instrument problem, not a wrong-document finding"
    )

    good = { "completion_abstract": "coined by Thelonius Quirke under Project Marble Fountain" }
    assert h.verify_content( {}, good ) == h.PASS

    wrong = { "completion_abstract": "a lengthy podcast about amateur ham radio antennas" }
    assert h.verify_content( {}, wrong ) == h.FAIL, "real text without the planted facts must still fail"
