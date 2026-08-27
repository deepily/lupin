"""
Find tests that drive code which reads LIVE session-bridge state without pinning it.

The failure this catches: _notify_impl's Phase-3 gate calls get_speakerphone( sid )
on every non-internal call. A test that does not pin it measures whichever box it
runs on — green on one machine, red on another, and green against a real defect
whenever the ambient value happens to sit on the harmless side.

Requires:
    - test_root is a directory of pytest files

Ensures:
    - one row per test FUNCTION that calls a bridge-reading entry point
    - reports whether that function, or its file, pins the bridge reader
    - reports only; touches nothing
"""
import os, re

TEST_ROOT = "/mnt/DATA01/include/www.deepily.ai/projects/lupin/src/tests"

# Entry points whose own code reads live bridge state on the way through.
# The per-driver counts caught two errors in this list on their first run, which
# is the reason they are printed at all:
#   · "_converse_impl" DOES NOT EXIST — the function is `converse` (:1337), and
#     it never reaches the gate. It matched nothing and inflated the apparent
#     breadth of this sweep from two drivers to three.
#   · "_flip_speakerphone" does not READ speakerphone state — it WRITES it via
#     set_speakerphone. Its 8 tests cannot carry this defect, so counting them
#     padded the denominator 33 -> 41.
# get_speakerphone has exactly ONE call site in cosa_voice_mcp.py — :1515, inside
# _notify_impl — so that is the whole scope of this detector. Bridge WRITES are a
# real but separate hazard and are deliberately out of scope here.
BRIDGE_DRIVERS = [ "_notify_impl" ]
# The readers a test must pin to be hermetic.
BRIDGE_READERS = [ "get_speakerphone", "_get_cc_metadata" ]

# ANY of these isolates the read, and a sweep that knows only one of them LIES.
# Measured 2026-08-26: keying on `monkeypatch.setattr` alone reported 8 flip tests
# as exposed when every one of them isolates via patch("...") plus a SESSION_DIR
# redirect into a tmpdir. Naming the isolators is the whole correctness of this.
ISOLATORS = [
    "get_speakerphone",      # the reader pinned directly, either patch style
    "_get_cc_metadata",      # sid pinned to a fake id: find_session_path_by_id misses
                             # and get_speakerphone returns False. NOTE this holds only
                             # while no real bridge carries that id — and NOT for a real
                             # sid whose bridge lacks the field, where the default is
                             # mode-aware and TRUE in chorus.
    "SESSION_DIR",           # bridge directory redirected — the read cannot find a live file
    "_internal_call",        # the gate is `if not _internal_call:` — the read never happens
    '"_notify_impl"',        # the driver itself is replaced, so the real one never runs
]

DEF     = re.compile( r"^(\s*)def (test_\w+)\s*\(", re.MULTILINE )
HELPER  = re.compile( r"(?:self|cls)\.(_\w+)\s*\(" )
HELPDEF = re.compile( r"^\s*def (_\w+)\s*\(", re.MULTILINE )

def helper_bodies( src ):
    """{ name: body } for each _private helper, so a pin inside one is visible.

    A shared arrange-helper is the NORMAL place to put these pins — three tests
    in one file isolate only through `self._arrange( ... )`. A sweep that reads
    test bodies alone calls all three exposed and sends someone to 'fix' code
    that was already correct."""
    marks = list( HELPDEF.finditer( src ) )
    out = {}
    for i, m in enumerate( marks ):
        end = marks[ i + 1 ].start() if i + 1 < len( marks ) else len( src )
        out[ m.group( 1 ) ] = src[ m.start():end ]
    return out

def functions( src ):
    """Yield ( name, body ) for each test function, body running to the next def."""
    marks = list( DEF.finditer( src ) )
    for i, m in enumerate( marks ):
        end  = marks[ i + 1 ].start() if i + 1 < len( marks ) else len( src )
        body = src[ m.start():end ]
        # STOP at a section divider or the next class. Without this the body
        # swallows the trailing "# ── _notify_impl fallbacks ──" header and a
        # test that never calls _notify_impl gets reported as driving it.
        cut = re.search( r"^(?:# ──|class )", body[ 1: ], re.MULTILINE )
        if cut: body = body[ : cut.start() + 1 ]
        yield m.group( 2 ), body

def classify( src, label="<memory>" ):
    """
    Rows for ONE source string: ( label, test_name, drivers, unpinned ).

    Split out from sweep() so the self-test below can feed it synthetic sources.
    A detector that can only be exercised against the tree it was tuned on cannot
    be shown to still detect anything.
    """
    rows = []
    if not any( d in src for d in BRIDGE_DRIVERS ): return rows
    # A file-level autouse fixture pinning a reader covers every test in it.
    file_pins = { r for r in ISOLATORS
                  if re.search( r"autouse=True[\s\S]{0,400}" + re.escape( r ), src ) }
    helpers = helper_bodies( src )
    for fn, body in functions( src ):
        # Inline any helper this test calls, so pins living there count.
        for h in HELPER.findall( body ):
            body += helpers.get( h, "" )
        drivers = sorted( { d for d in BRIDGE_DRIVERS if d in body } )
        if not drivers: continue
        # Exposed only when NO isolator appears — any one of them is enough.
        isolated = [ i for i in ISOLATORS if i in body or i in file_pins ]
        unpinned = [] if isolated else [ "get_speakerphone" ]
        rows.append( ( label, fn, drivers, unpinned ) )
    return rows


def sweep( test_root=TEST_ROOT ):
    """Every test under test_root, classified. Reports only; touches nothing."""
    rows = []
    for dirpath, _dirs, files in os.walk( test_root ):
        if "/logs" in dirpath: continue
        for name in files:
            if not name.endswith( ".py" ): continue
            path = os.path.join( dirpath, name )
            src  = open( path, encoding="utf-8", errors="replace" ).read()
            rows += classify( src, os.path.relpath( path, test_root ) )
    return rows


# ── The positive control travels WITH the detector ───────────────────────────
# Mr Radio's point, 2026-08-26: "0 of 41", measured on the tree this was tuned
# against, is fitted to the data. A sweep that has quietly STOPPED DETECTING
# reports the same 0 as a genuinely clean tree, and nothing in that number tells
# the two apart. So the control lives here and runs on every invocation.

_EXPOSED = (
    "class TestProbe:\n"
    "    def test_it_drives_the_real_impl_unpinned( self, monkeypatch ):\n"
    "        cv._notify_impl( \"hello\" )\n"
)

# One line per isolator the sweep claims to recognise. If any stops being seen,
# the sweep starts inventing work — which is the failure that cost an evening.
_ISOLATED = {
    "direct pin"      : "        monkeypatch.setattr( sb, \"get_speakerphone\", lambda sid: False )\n",
    "sid pinned"      : "        monkeypatch.setattr( cv, \"_get_cc_metadata\", lambda: {} )\n",
    "dir redirected"  : "        monkeypatch.setattr( sb, \"SESSION_DIR\", tmp )\n",
    "internal call"   : "        cv._notify_impl( \"hello\", _internal_call=True )\n",
    "driver replaced" : "        monkeypatch.setattr( cv, \"_notify_impl\", lambda **k: \"sent\" )\n",
}


def self_test():
    """
    Prove the detector still fires, and still stays quiet.

    Ensures:
        - returns [] when the negative control is flagged and every isolator is
          recognised; otherwise one string per failure, naming which
    """
    bad = []
    if not [ r for r in classify( _EXPOSED, "probe" ) if r[ 3 ] ]:
        bad.append( "NEGATIVE CONTROL FAILED: an unpinned driver was NOT flagged — "
                    "the sweep has stopped detecting and its 0 means nothing" )
    for name, line in _ISOLATED.items():
        if [ r for r in classify( _EXPOSED + line, "probe" ) if r[ 3 ] ]:
            bad.append( f"FALSE POSITIVE: isolator no longer recognised — {name}" )
    return bad


# ── Exit codes ────────────────────────────────────────────────────────────────
# A caller has to tell "the detector is broken" from "the detector found work",
# and a single non-zero conflates them: the first is urgent and means every other
# number in the run is worthless, the second is ordinary and means there is a
# test to pin. EXIT_BROKEN takes precedence — when the self-test fails, the
# sweep's own count is not evidence of anything and must not be acted on.
EXIT_CLEAN  = 0     # self-test passed, nothing unpinned
EXIT_WORK   = 1     # self-test passed, unpinned tests found — go pin them
EXIT_BROKEN = 2     # self-test FAILED — the detector is untrustworthy, ignore its count


def _driver_counts( rows ):
    """Tests seen per driver — a driver contributing 0 is a blinded sweep, visibly.

    Mr Radio, 2026-08-26: blinding the detector dropped the total 41 -> 8, and
    "that drop is itself a tell, but only to someone who remembers 41." Nobody
    remembers 41. A per-driver line needs no memory: `_notify_impl: 0` is wrong
    on its face. A hardcoded expected total would rot as the tree grows; this
    does not.
    """
    return { d: sum( 1 for r in rows if d in r[ 2 ] ) for d in BRIDGE_DRIVERS }


if __name__ == "__main__":
    import sys

    failures = self_test()
    for f in failures: print( f"WARNING  {f}" )
    print( f"self-test: {'PASSED' if not failures else 'FAILED'} "
           f"(1 negative control + {len( _ISOLATED )} isolators)\n" )

    rows = sweep()
    bad  = [ r for r in rows if "get_speakerphone" in r[ 3 ] ]
    print( f"{len( rows )} test(s) drive bridge-reading code; {len( bad )} do NOT pin get_speakerphone" )
    for driver, n in sorted( _driver_counts( rows ).items() ):
        flag = "   <- ZERO: this driver is not being seen at all" if n == 0 else ""
        print( f"    {driver:<20} {n:>3}{flag}" )
    print()

    seen = None
    for rel, fn, drivers, unpinned in sorted( bad ):
        if rel != seen:
            print( f"  {rel}" ); seen = rel
        print( f"      {fn}  ->  {', '.join( drivers )}  [unpinned: {', '.join( unpinned )}]" )

    if failures:
        print( "\nThe self-test failed, so the counts above are NOT evidence — fix the "
               "detector before acting on them." )
        sys.exit( EXIT_BROKEN )
    sys.exit( EXIT_WORK if bad else EXIT_CLEAN )
