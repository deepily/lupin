"""
Revert arms for row 6ce9f4a1: undo ONE escapeHtml wrap at a time in notifications.js, run the
escaping test file, and record which named tests fail. Restores the file byte-for-byte after every
arm and proves it (sha256 before == after). Run from the worktree root:

    python3 src/rnd/assets/2026.09.11-legacy-escaping-sweep/revert_arms.py
"""
import hashlib, re, subprocess, sys

JS   = "src/lupin_app/static/js/notifications.js"
TEST = "src/tests/unit/notifications_js/sender_text_is_escaped_in_the_legacy_page.test.ts"

# ( anchor that must match exactly once, its pre-fix form, the test expected to redden )
ARMS = [
    ( "${this.escapeHtml( errorText )}",                                   "${errorText}",                                   "TTS error modal: the error TEXT renders as text" ),
    ( "${this.escapeHtml( errorCode )}",                                   "${errorCode}",                                   "TTS error modal: the error CODE renders as text" ),
    ( "${this.escapeHtml( sessionName || '' )}",                           "${sessionName || ''}",                           "sender card: a session name renders as text" ),
    ( "${this.escapeHtml( truncatedMessage )}",                            "${truncatedMessage}",                            "minimized action-required card: the message renders as text" ),
    ( "${this.escapeHtml( notification.response_default || '' )}",        "${notification.response_default || ''}",        "action-required card: an open-ended response_default stays inside value=\"…\"" ),
    ( "${this.escapeHtml( notification.title || notification.message )}",  "${notification.title || notification.message}",  "action-required card: the TITLE renders as text" ),
    ( "value=\"${this.escapeHtml( opt.label )}\"",                         "value=\"${opt.label}\"",                         "multiple choice: an option LABEL stays inside the input's value=\"…\"" ),
    ( "mc-option-label\">${this.escapeHtml( opt.label )}",                 "mc-option-label\">${opt.label}",                 "multiple choice: an option LABEL renders as text" ),
    ( "${this.escapeHtml( opt.description || '' )}",                       "${opt.description || ''}",                       "multiple choice: an option DESCRIPTION renders as text" ),
    ( "value=\"${this.escapeHtml( otherText )}\"",                         "value=\"${otherText}\"",                         "multiple choice: the operator's saved 'Other' answer stays inside value=\"…\"" ),
    ( "${this.escapeHtml( question.question )}",                           "${question.question}",                           "multiple choice: the QUESTION renders as text" ),
    ( "Default used: ${this.escapeHtml( defaultValue )}",                  "Default used: ${defaultValue}",                  "expired badge: the sender's response_default renders as text" ),
    ( "another session: ${this.escapeHtml( response )}",                   "another session: ${response}",                   "responded-in-another-session badge: the response renders as text" ),
    ( "${this.escapeHtml( predictedText )}",                               "${predictedText}",                               "prediction hint: a predicted answer's header renders as text" ),
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
if base_failed: sys.exit( "baseline is not green — refusing to score arms" )

bad = 0
for i, ( anchor, prefix, expected ) in enumerate( ARMS, 1 ):
    text  = original.decode()
    count = text.count( anchor )
    if count != 1:
        print( f"arm {i:2d}: ANCHOR MATCHED {count} TIMES — not applied: {anchor}" ); bad += 1; continue
    mutated = text.replace( anchor, prefix ).encode()
    open( JS, "wb" ).write( mutated )
    assert sha( open( JS, "rb" ).read() ) != sha( original ), "mutation did not change the file"
    failed, total = run_tests()
    open( JS, "wb" ).write( original )
    restored = sha( open( JS, "rb" ).read() ) == sha( original )
    ok = expected in failed and total == base_total and restored
    bad += 0 if ok else 1
    extra = [ f for f in failed if f != expected ]
    print( f"arm {i:2d}: {'KILLED ' if expected in failed else 'SURVIVED'} ran={total} failing={len( failed )} restored={restored}  expected: {expected}" + ( f"  ALSO: {extra}" if extra else "" ) )

final_failed, _ = run_tests()
print( f"restore control: sha={sha( open( JS, 'rb' ).read() )} (== {sha( original )}), failing after restore={final_failed}" )
sys.exit( 1 if bad or final_failed else 0 )
