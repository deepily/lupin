"""
Revert arms for row b5e13bd0 (addNotificationToList): undo ONE change at a time in notifications.js,
run the escaping test file, and record which named tests fail. Restores the file byte-for-byte after
every arm and proves it (sha256 before == after). Run from the worktree root:

    python3 src/rnd/assets/2026.09.11-legacy-escaping-sweep/revert_arms_list.py

An arm whose `expected` is empty is an EQUIVALENT mutant: it must change the file and redden nothing.
"""
import hashlib, re, subprocess, sys

JS   = "src/lupin_app/static/js/notifications.js"
TEST = "src/tests/unit/notifications_js/sender_text_is_escaped_in_the_legacy_page.test.ts"

UNPREFIXED_FIXED = 'displayMessage = this.escapeHtml( message.length > 80 ? message.substring( 0, 77 ) + "..." : message );'
MARKUP           = "`<strong><em>${prefix}:</em></strong> `.length"

# ( name, [ ( anchor that must match exactly once, its reverted form ) ], tests expected to redden )
ARMS = [
    ( "rest of a prefixed line unescaped",
      [ ( "${this.escapeHtml( shownRemainder )}", "${shownRemainder}" ) ],
      [ "notification list: the text after a [PREFIX] renders as text" ] ),
    ( "unprefixed line unescaped",
      [ ( UNPREFIXED_FIXED, 'displayMessage = message.length > 80 ? message.substring( 0, 77 ) + "..." : message;' ) ],
      # The cut test guards this site too: unescaped, its "<..." is parsed as markup, not shown.
      [ "notification list: a message with no prefix renders as text",
        "notification list: the cut lands on the raw text, so a '<' at character 77 is shown, not a broken entity" ] ),
    ( "title unescaped",
      [ ( 'title="${this.escapeHtml( message )}"', 'title="${message}"' ) ],
      [ "notification list: the message stays inside title=\"…\"" ] ),
    ( "escape BEFORE the cut (unprefixed)",
      [ ( UNPREFIXED_FIXED, 'displayMessage = ( s => s.length > 80 ? s.substring( 0, 77 ) + "..." : s )( this.escapeHtml( message ) );' ) ],
      [ "notification list: the cut lands on the raw text, so a '<' at character 77 is shown, not a broken entity" ] ),
    ( "the limit counts the prefix markup again",
      [ ( "prefix.length + 2 + remainingMessage.length", f"{MARKUP} + remainingMessage.length" ),
        ( "77 - prefix.length - 2", f"77 - {MARKUP}" ) ],
      [ "notification list: with a [PREFIX], the 80-character limit counts what is shown, not the markup",
        "notification list: a [PREFIX] line of exactly 80 shown characters is not cut, and 81 is" ] ),
    ( "prefix unescaped (EQUIVALENT: the regex admits only A-Z)",
      [ ( "${this.escapeHtml( prefix )}", "${prefix}" ) ],
      [ ] ),
]

def sha( b ): return hashlib.sha256( b ).hexdigest()[ :12 ]

def run_tests():
    cmd = f'source src/scripts/lib/jstest-slice.sh; LUPIN_ROOT="$PWD" jstest_slice_exec timeout 120 node --import tsx --test {TEST}'
    out = subprocess.run( [ "bash", "-c", cmd ], capture_output=True, text=True ).stdout
    failed = re.findall( r"^not ok \d+ - (.+)$", out, re.M )
    total  = re.search( r"^# tests (\d+)", out, re.M )
    return failed, int( total.group( 1 ) ) if total else -1

original = open( JS, "rb" ).read()
base_failed, base_total = run_tests()
print( f"baseline: {base_total} tests, failing={base_failed}  sha={sha( original )}" )
if base_failed or base_total < 1: sys.exit( "baseline is not green — refusing to score arms" )

bad = 0
for i, ( name, edits, expected ) in enumerate( ARMS, 1 ):
    text = original.decode()
    counts = [ text.count( anchor ) for anchor, _ in edits ]
    if counts != [ 1 ] * len( edits ):
        print( f"arm {i}: ANCHOR COUNTS {counts} — not applied: {name}" ); bad += 1; continue
    for anchor, reverted in edits: text = text.replace( anchor, reverted )
    open( JS, "wb" ).write( text.encode() )
    changed = sha( open( JS, "rb" ).read() ) != sha( original )
    failed, total = run_tests()
    open( JS, "wb" ).write( original )
    restored = sha( open( JS, "rb" ).read() ) == sha( original )
    ok = changed and restored and total == base_total and sorted( failed ) == sorted( expected )
    bad += 0 if ok else 1
    verdict = ( "KILLED  " if failed else "SURVIVED" ) if expected else ( "EQUIV-OK" if not failed else "EQUIV-RED" )
    print( f"arm {i}: {verdict} ran={total} failing={failed} changed={changed} restored={restored}  ({name})" + ( "" if ok else "  <-- UNEXPECTED" ) )

final_failed, final_total = run_tests()
print( f"restore control: sha={sha( open( JS, 'rb' ).read() )} (== {sha( original )}), ran={final_total}, failing after restore={final_failed}" )
sys.exit( 1 if bad or final_failed else 0 )
