"""Time /api/upload-and-transcribe-wav on :7999 with REAL speech (row 9df9f1c2, Rick ruled ~22:29 EDT 2026-09-10).

Source: a Lupin podcast MP3 (two synthetic-voice hosts reading a written script), cut with ffmpeg to 16 kHz mono
PCM WAV at ~5 / 15 / 30 s. The podcast's own script is the reference text: each returned transcript is scored by
the best word-level match against a same-length window of that script, so "it returned the spoken words" is
measured, not eyeballed.
Two passes over the three clips (6 POSTs, 6 InputAndOutputTable rows), so a cold first call is visible.
"""
import difflib, json, os, re, subprocess, sys, time, wave
from datetime import datetime

import requests

SP     = sys.argv[ 1 ]
L      = "/mnt/DATA01/include/www.deepily.ai/projects/lupin"
MP3    = f"{L}/io/podcasts/ricardo.felipe.ruiz@gmail.com/2026.03.03-220744-teaching-ai-to-make-decisions-the-trust.mp3"
SCRIPT = f"{L}/io/podcasts/ricardo.felipe.ruiz@gmail.com/2026.03.03-220711-teaching-ai-to-make-decisions-the-trust-script.md"
URL    = "http://localhost:7999/api/upload-and-transcribe-wav"
CLIPS  = [ ( "5s", 31.0, 5.0 ), ( "15s", 61.0, 15.0 ), ( "30s", 121.0, 30.0 ) ]   # ( label, offset s, duration s )

def words( text ): return re.findall( r"[a-z0-9']+", text.lower() )

# Reference: the spoken lines only — drop headings, speaker tags and *[stage directions]*.
ref_lines = []
for line in open( SCRIPT, encoding="utf-8" ):
    if not line.startswith( "**[" ): continue
    body = re.sub( r"^\*\*\[[^\]]*\]\*\*:\s*", "", line )
    body = re.sub( r"\*\[[^\]]*\]\*", " ", body )
    ref_lines.append( body )
REF = words( " ".join( ref_lines ) )

def best_match( hyp ):
    """Best SequenceMatcher ratio of hyp against any same-length window of the script (step 1 word)."""
    n = len( hyp )
    if n == 0: return 0.0, ""
    best, where = 0.0, 0
    for i in range( 0, max( 1, len( REF ) - n + 1 ) ):
        r = difflib.SequenceMatcher( None, hyp, REF[ i:i + n ], autojunk=False ).ratio()
        if r > best: best, where = r, i
    return best, " ".join( REF[ where:where + n ] )

rows = []
for label, off, dur in CLIPS:
    wav = os.path.join( SP, f"speech-{label}.wav" )
    subprocess.run( [ "ffmpeg", "-v", "error", "-y", "-ss", str( off ), "-t", str( dur ), "-i", MP3,
                      "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", wav ], check=True )
    with wave.open( wav ) as w:
        assert w.getframerate() == 16000 and w.getnchannels() == 1, "not 16 kHz mono"
        actual = w.getnframes() / w.getframerate()
    rows.append( ( label, wav, actual, os.path.getsize( wav ) ) )

results = []
for p in ( 1, 2 ):
    for label, wav, actual, size in rows:
        with open( wav, "rb" ) as fh:
            payload = fh.read()
        stamp = datetime.now().astimezone().isoformat( timespec="seconds" )
        t0 = time.perf_counter()
        resp = requests.post( URL, files={ "file": ( os.path.basename( wav ), payload, "audio/wav" ) }, timeout=300 )
        elapsed = time.perf_counter() - t0
        try:
            text = resp.json()
            if not isinstance( text, str ): text = json.dumps( text )
        except ValueError:
            text = resp.text
        hyp = words( text )
        ratio, ref_window = best_match( hyp )
        r = { "pass": p, "clip": label, "audio_s": round( actual, 3 ), "upload_kb": round( size / 1024, 1 ),
              "status": resp.status_code, "elapsed_s": round( elapsed, 3 ), "rtf": round( elapsed / actual, 3 ),
              "words": len( hyp ), "script_match": round( ratio, 3 ), "at": stamp, "text": text, "ref_window": ref_window }
        results.append( r )
        print( json.dumps( r, ensure_ascii=False ), flush=True )

json.dump( results, open( os.path.join( SP, "transcribe-real-speech-results.json" ), "w" ), indent=2, ensure_ascii=False )
