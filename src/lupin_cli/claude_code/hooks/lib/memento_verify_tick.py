"""
The standing tick for `memento_io.py verify` — row 505e5c12.

WHY THIS EXISTS. `verify` checks that every memento RECORD in this repo is byte-identical
to its out-of-repo mirror, and that no record content is sitting at a POINTER path where
the next pointer write would destroy it. Nothing called it. Cheech found it by reading a
warning the tool prints about itself and running it by hand — after 6 days 14 hours unrun,
with real findings waiting, including a bare slot, which is a data-loss window rather than
a tidiness complaint.

THE SHAPE, in the row's words: a check that cannot fire is indistinguishable from a check
that passes. The mirror-integrity guarantee had been resting on somebody happening to
notice a warning.

THE THREE DECISIONS THE ROW LEFT OPEN, and how they are answered here — argue with these
rather than assume they were defaults:

  WHERE. The Stop hook, behind a TTL ledger. It is the only surface that already runs
  unattended on every seat without new infrastructure — no systemd unit to install, no
  cron to survive a reboot, nothing to remember. A session-scoped cron was the obvious
  alternative and it is wrong for exactly the reason this row exists: it dies with the
  session that created it, so the check would go quiet the moment its owner was reaped
  and nobody would be told.

  CADENCE. Daily. This is a whole-repo scan of a few hundred small files against their
  mirrors; hourly buys nothing (mementos are written a handful of times a day) and turns
  a real finding into wallpaper. `MEMENTO_VERIFY_TTL_SECONDS` is one constant.

  WHAT IT DOES WITH A FINDING. It SAYS SO. It never restores, never deletes, never
  migrates. The row flagged auto-restore as "tempting and probably wrong without a human
  look" and it is right: an orphan mirror can mean "deliberately deleted" exactly as
  easily as "lost", and those two want opposite actions. A tick that guesses between them
  will eventually resurrect something somebody removed on purpose.

CROSS-REPO, AND WHY THAT IS FINE HERE. `memento_io.py` lives in planning-is-prompting and
is reached through `PLANNING_IS_PROMPTING_ROOT`, the env var CLAUDE.md already designates
for exactly this. The RECORDS it verifies live in THIS repo (`io/mementos/`), so a
Lupin-side tick over Lupin's own mementos is in-lane. If the env var is unset or the
script is missing, this reports that plainly and returns — it does not guess a path.

⚠️ IT FAILS SOFT, ALWAYS. Every path returns a string and swallows its own exceptions. A
memento checker that could take the Stop hook down would be a worse bug than the one it
was written to catch.

⚠️ AND IT NEVER GOES SILENT ON AN ERROR. A timeout, a missing script, an unreadable
ledger — each returns a LOUD line, never "". Silence is reserved for the two states that
genuinely mean nothing-to-say: the TTL has not expired, or the run found nothing. That
distinction is the entire point of the row.
"""

import json
import os
import subprocess

from datetime import datetime, timezone
from pathlib import Path

from lupin_cli.claude_code.hooks.lib.sessions_dir import sessions_dir

# One scan per day. See CADENCE above.
MEMENTO_VERIFY_TTL_SECONDS = 24 * 3600

# The scan walks a few hundred files and hashes each against its mirror. Generous, because
# the cost of a false "timed out" line is a reader chasing a problem that is not there.
MEMENTO_VERIFY_TIMEOUT_SECONDS = 120

_LEDGER_NAME = ".memento-verify-tick.json"


def _ledger_path():
    """
    Where the last-run stamp lives.

    Ensures:
        - returns a Path under the SAME sessions dir the other hook ledgers use, so
          this one is not a second convention nobody thinks to look for
    """
    return Path( sessions_dir() ) / _LEDGER_NAME


def _read_last_run( path, now ):
    """
    Seconds since the last recorded run, or None when there is no usable stamp.

    Requires:
        - path is a Path; now is a timezone-aware datetime

    Ensures:
        - returns None when the file is absent, unparseable, or carries no timestamp —
          all three mean "never ran as far as anyone can tell", which must trigger a run
          rather than suppress one. A ledger that cannot be read is not a ledger that
          says "recently done".
    """
    try:
        if not path.exists(): return None
        stamp = json.loads( path.read_text( encoding="utf-8" ) ).get( "last_run" )
        if not stamp: return None
        return ( now - datetime.fromisoformat( stamp ) ).total_seconds()
    except Exception:
        return None


def _write_last_run( path, now, findings ):
    """
    Stamp this run.

    Ensures:
        - records the timestamp and the finding count; a write failure is swallowed,
          because losing the stamp costs one extra scan tomorrow and taking the hook
          down costs the session
    """
    try:
        path.parent.mkdir( parents=True, exist_ok=True )
        path.write_text(
            json.dumps( { "last_run": now.isoformat(), "findings": findings }, indent=2 ),
            encoding="utf-8",
        )
    except Exception:
        pass


def _script_path():
    """
    The memento_io.py this tick drives, or None when it cannot be located.

    Ensures:
        - resolves ONLY from PLANNING_IS_PROMPTING_ROOT — never a guessed relative path.
          A wrong guess would run some other copy of the script against this repo, and
          a checker pointed at the wrong tree is worse than no checker
    """
    root = os.environ.get( "PLANNING_IS_PROMPTING_ROOT" )
    if not root: return None
    path = Path( root ) / "workflow" / "scripts" / "memento_io.py"
    return path if path.exists() else None


def _parse_findings( stdout ):
    """
    The finding count from verify's own summary line.

    Requires:
        - stdout is the captured text of a verify run

    Ensures:
        - returns an int when a `--- FINDINGS : N` line is present
        - returns None when it is not — and None is NOT zero. A run whose output we
          cannot read has not been shown to be clean, and rendering it as 0 findings is
          precisely the "could not measure" wearing "measured, fine" costume this whole
          area of the codebase keeps getting bitten by
    """
    for line in reversed( stdout.splitlines() ):
        if "FINDINGS" in line and ":" in line:
            try:
                return int( line.split( ":" )[ -1 ].strip() )
            except ValueError:
                return None
    return None


def verify_tick_line( repo_root=None, now=None, force=False ):
    """
    Run `memento_io.py verify` at most once a day and return one line about it.

    Requires:
        - repo_root is the repo whose mementos are checked (defaults to LUPIN_ROOT)
        - now is a timezone-aware datetime (defaults to real now)
        - force=True bypasses the TTL, for the CLI and for tests

    Ensures:
        - returns "" ONLY when the TTL has not expired, or the run found nothing —
          the two states that genuinely mean nothing to say
        - returns a LOUD line on every failure (no env var, missing script, timeout,
          unreadable output), never ""
        - NEVER restores, deletes, or migrates anything; it reports
        - never raises
    """
    try:
        now  = now or datetime.now( timezone.utc )
        path = _ledger_path()

        if not force:
            age = _read_last_run( path, now )
            if age is not None and age < MEMENTO_VERIFY_TTL_SECONDS: return ""

        script = _script_path()
        if script is None:
            _write_last_run( path, now, None )
            return ( "⚠️ memento verify SKIPPED — PLANNING_IS_PROMPTING_ROOT is unset or "
                     "workflow/scripts/memento_io.py is missing. The mirror-integrity check "
                     "has not run; this is not a clean result." )

        repo_root = repo_root or os.environ.get( "LUPIN_ROOT" )
        if not repo_root:
            _write_last_run( path, now, None )
            return "⚠️ memento verify SKIPPED — LUPIN_ROOT is unset, so there is no repo to check."

        try:
            proc = subprocess.run(
                [ "python", str( script ), "verify", "--repo", str( repo_root ) ],
                capture_output=True, text=True, timeout=MEMENTO_VERIFY_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            _write_last_run( path, now, None )
            return ( f"⚠️ memento verify TIMED OUT after {MEMENTO_VERIFY_TIMEOUT_SECONDS}s. "
                     "Mirror integrity is UNVERIFIED, not confirmed." )

        findings = _parse_findings( proc.stdout )
        _write_last_run( path, now, findings )

        if findings is None:
            return ( "⚠️ memento verify ran but its FINDINGS line could not be read, so the "
                     "result is unknown rather than clean. Re-run it by hand: "
                     "memento_io.py verify --repo <lupin>" )
        if findings == 0:
            return ""
        return ( f"⚠️ memento verify: {findings} finding(s) in this repo's mementos. "
                 "A BARE-SLOT is a live data-loss window — the next pointer write destroys "
                 "the record. Preserve first: memento_io.py migrate --repo <lupin> --apply. "
                 "Nothing has been changed for you." )
    except Exception as e:
        return ( f"⚠️ memento verify tick failed ({type( e ).__name__}). Mirror integrity is "
                 "UNVERIFIED — this is not a clean result." )


def quick_smoke_test():
    """Exercise the tick's decision paths without touching the real ledger."""
    import tempfile

    print( "Testing memento_verify_tick..." )
    passed = failed = 0
    now = datetime.now( timezone.utc )

    print( "\n1. A fresh stamp suppresses the run..." )
    try:
        with tempfile.TemporaryDirectory() as d:
            p = Path( d ) / "l.json"
            _write_last_run( p, now, 0 )
            assert _read_last_run( p, now ) < 5
            print( "   ✓ recent stamp reads as recent" ); passed += 1
    except Exception as e:
        print( f"   ✗ {type( e ).__name__}: {e}" ); failed += 1

    print( "\n2. An unreadable ledger reads as NEVER RAN, not as recent..." )
    try:
        with tempfile.TemporaryDirectory() as d:
            p = Path( d ) / "l.json"
            p.write_text( "not json", encoding="utf-8" )
            assert _read_last_run( p, now ) is None
            print( "   ✓ garbage ledger triggers a run rather than suppressing one" ); passed += 1
    except Exception as e:
        print( f"   ✗ {type( e ).__name__}: {e}" ); failed += 1

    print( "\n3. An unreadable FINDINGS line is None, never 0..." )
    try:
        assert _parse_findings( "no summary here" ) is None
        assert _parse_findings( "--- FINDINGS    : 3" ) == 3
        assert _parse_findings( "--- FINDINGS    : 0" ) == 0
        print( "   ✓ unknown and zero stay distinguishable" ); passed += 1
    except Exception as e:
        print( f"   ✗ {type( e ).__name__}: {e}" ); failed += 1

    print( f"\n{passed} passed, {failed} failed" )
    return failed == 0


if __name__ == "__main__":
    import sys
    if "--smoke" in sys.argv:
        sys.exit( 0 if quick_smoke_test() else 1 )
    line = verify_tick_line( force=True )
    print( line or "memento verify: no findings" )
