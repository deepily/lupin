"""
Stop-sentinel probe — one message, prompt printed verbatim, output streamed.

    export LUPIN_ROOT=/mnt/DATA01/include/www.deepily.ai/projects/lupin
    cd $LUPIN_ROOT
    python src/rnd/v0.2.0/2026.08.04-dm-verbosity-reduction/stop_probe.py            # as-is
    python src/rnd/v0.2.0/2026.08.04-dm-verbosity-reduction/stop_probe.py --sentinel # + emit </stop>
    python .../stop_probe.py --both                                                  # run both, compare

THE HYPOTHESIS (Rick, 2026-08-11): the run never stops because the sentinel is
configured on the SERVER side but never requested in the PROMPT.

    lupin-app.ini:219  "stop": [ "</s>", "</stop>" ]

vLLM will happily halt on `</stop>` — but only if the model emits it, and
nothing in `dm.txt` ever asks the model to. A stop list is a catcher, not an
instruction. So the model finishes its answer, receives no reason to halt, and
keeps generating until `max_tokens` 4096. That is the 56-second, 3,004-word call.

This script exists to make that visible rather than argued:

  1. the OUTBOUND PROMPT is printed verbatim — every character the model sees,
     so anyone can check for themselves whether `</stop>` appears in it;
  2. the configured stop list is printed beside it;
  3. the response is STREAMED to the console, so a loop is watched happening
     rather than inferred from a duration;
  4. `--sentinel` appends the one instruction the prompt is missing, and
     `--both` runs the pair back to back so the difference is the only variable.

Fixed on the 250+ message that took 56.5s — the slowest of the three bands, and
the one where the loop reproduces.
"""

import json
import pathlib
import sys
import time

sys.path.insert( 0, "src" )

from cosa.agents.llm_client_factory import LlmClientFactory

SNAPSHOT = "src/tmp/arm4/dm_traffic_snapshot_2026.08.07.jsonl"
TEMPLATE = "src/conf/prompts/agents/dm.txt"
MODEL    = "dm_compression/phi_4"

# ⚠️ DELIBERATELY FOUR SLOTS, unlike dm_txt_run.py, which gained a fifth
# (<file-path-or-url-if-present>) on 2026-08-11. This probe is the instrument
# that produced the stop-sentinel numbers — 3,004 words in 56.2s against 114 in
# 3.2s — and those belong to the four-slot prompt. Widening the scaffold here
# would silently re-point the comparison at a prompt that was never measured.
# Re-run this probe against the five-slot scaffold only as a NEW measurement.
XML_EXAMPLE = (
    "<response>\n"
    "  <thoughts>Your reasoning about what this DM is actually saying</thoughts>\n"
    "  <declaration-or-question>The single most important declaration, or the most "
    "important question asked</declaration-or-question>\n"
    "  <supporting-statement-1st>The first supporting statement</supporting-statement-1st>\n"
    "  <supporting-statement-2nd>The second supporting statement</supporting-statement-2nd>\n"
    "</response>"
)

# The one line the prompt is missing. Deliberately minimal: it asks for the
# sentinel the server is ALREADY configured to stop on, and nothing else, so a
# difference between the two runs cannot be attributed to any other wording.
SENTINEL_LINE = (
    "\nRequirement: After the closing </response> tag, you MUST emit "
    "</stop> and then write nothing further.\n"
)


def pick_body():
    """
    The 250+ message this probe is fixed on.

    Requires:
        - SNAPSHOT is the pinned corpus

    Ensures:
        - returns the same body every run — the middle of the 250+ pool, which
          is the message dm_txt_run.py measured at 56.5s and 3,004 words

    Raises:
        - SystemExit if the corpus is missing
    """
    if not pathlib.Path( SNAPSHOT ).exists():
        sys.exit( f"corpus missing: {SNAPSHOT} — see CORPUS-MANIFEST.md" )

    pool = []
    for line in open( SNAPSHOT ):
        line = line.strip()
        if not line: continue
        try: record = json.loads( line )
        except Exception: continue
        body = record.get( "body" )
        if body and len( body.split() ) >= 250: pool.append( body )

    return pool[ len( pool ) // 2 ]


def build_prompt( body, with_sentinel ):
    """
    Assemble the outbound prompt.

    Requires:
        - body is the DM to distil
        - with_sentinel selects whether the </stop> instruction is added

    Ensures:
        - returns the exact string sent to the model
        - the sentinel line, when added, sits with the other Requirements rather
          than after the message it governs

    Raises:
        - nothing
    """
    template = pathlib.Path( TEMPLATE ).read_text()
    if with_sentinel:
        template = template.replace( "### Input:", SENTINEL_LINE + "\n### Input:", 1 )
    return template.replace( "{{PYDANTIC_XML_EXAMPLE}}", XML_EXAMPLE ).replace( "{dm}", body )


def probe( client, prompt, label ):
    """
    Send one prompt and stream the response to the console.

    Requires:
        - client is an initialized LLM client
        - prompt is the assembled outbound text

    Ensures:
        - prints the response as it arrives, so a runaway is watched, not inferred
        - returns ( text, seconds )
        - never raises — a failure is printed and returned as empty text

    Raises:
        - nothing
    """
    print( f"\n{'=' * 78}\nSTREAMING — {label}\n{'=' * 78}", flush=True )

    started = time.time()
    try:
        text = client.run( prompt, stream=True )
    except Exception as e:
        print( f"\n🔴 {type( e ).__name__}: {e}", flush=True )
        return "", time.time() - started
    elapsed = time.time() - started

    if text and not sys.stdout.isatty(): print( text, flush=True )

    print( f"\n{'-' * 78}" )
    print( f"{label}: {len( text.split() )} words · {elapsed:.1f}s"
           f" · ends with </stop>: {text.rstrip().endswith( '</stop>' )}" )
    print( f"contains </response>: {'</response>' in text}"
           f" · text after </response>: "
           f"{len( text.split( '</response>' )[ -1 ].split() ) if '</response>' in text else 'n/a'} words" )
    return text, elapsed


def main():
    body   = pick_body()
    client = LlmClientFactory().get_client( MODEL )

    arms = [ ( "WITH </stop> requested", True ) ] if "--sentinel" in sys.argv else \
           [ ( "AS-IS (no sentinel requested)", False ) ]
    if "--both" in sys.argv:
        arms = [ ( "AS-IS (no sentinel requested)", False ), ( "WITH </stop> requested", True ) ]

    print( "=" * 78 )
    print( "CONFIGURED STOP LIST (server side)" )
    print( "=" * 78 )
    print( f"  {client.generation_args.get( 'stop' )}" )
    print( f"  max_tokens: {client.generation_args.get( 'max_tokens' )}"
           f"  ·  temperature: {client.generation_args.get( 'temperature' )}" )
    print( "\n⚠️ A stop list is a CATCHER, not an instruction. If the prompt below never" )
    print( "   asks the model to emit </stop>, the server has nothing to catch." )

    results = []
    for label, with_sentinel in arms:
        prompt = build_prompt( body, with_sentinel )

        print( "\n" + "=" * 78 )
        print( f"OUTBOUND PROMPT — {label} · {len( prompt )} chars" )
        print( "=" * 78 )
        print( prompt )
        print( "=" * 78 )
        print( f"'</stop>' present in prompt: {'</stop>' in prompt}" )

        text, elapsed = probe( client, prompt, label )
        results.append( ( label, len( text.split() ), elapsed ) )

    if len( results ) > 1:
        print( "\n" + "=" * 78 )
        print( f"{'arm':<34}{'words':>8}{'secs':>8}" )
        for label, wordcount, secs in results:
            print( f"{label:<34}{wordcount:>8}{secs:>8.1f}" )


if __name__ == "__main__":
    main()
