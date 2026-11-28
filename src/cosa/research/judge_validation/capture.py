"""
Capture real judge replies into committed fixtures, and replay them to the real reader.

A fixture is one case from minimal_pairs.json, run through answer_judge.make_judge against a real
model through bounded Claude Code. It keeps each call's model, system prompt, user prompt and raw
reply, with the verdict the judge read from that reply. The replay answers only a request it has
recorded, so a changed prompt is refused instead of being handed an old reply. The one part it
ignores is the random suffix on the prompt's tags, which differs on every call.

Run it from the repository root, after a prompt change:

    python -m cosa.research.judge_validation.capture
"""

import argparse
import datetime
import json
import os
import re

import cosa.utils.util as cu
from cosa.agents.prediction_engine.answer_judge import judge_model, make_judge
from cosa.repo.doc_lint import model_transport

PAIRS_PATH  = "/src/cosa/research/judge_validation/minimal_pairs.json"
FIXTURE_DIR = "/src/tests/fixtures/answer_judge"

# ( side name, the case's key for the forecast, whether the judge should pass it )
SIDES = ( ( "matching", "matching_text", True ), ( "altered", "altered_text", False ) )


# The tags answer_judge puts round the two texts end in a random suffix.
TAG_SUFFIX = re.compile( r"(</?(?:actual|predicted))_[0-9a-f]{8}>" )


def _request_key( model_id, system_prompt, user_prompt ):
    """
    Name a request by everything but its random tag suffix.

    Requires:
        - the three arguments are strings

    Ensures:
        - returns the three, with the suffix removed from the user prompt's tags
    """
    return ( model_id, system_prompt, TAG_SUFFIX.sub( r"\1>", user_prompt ) )


def load_cases( path=None ):
    """
    Read the cases the fixtures are captured from, which are not among the 24 minimal pairs.

    Requires:
        - path is None, for the committed minimal_pairs.json, or a file of the same shape

    Ensures:
        - returns { kind: case } for every entry of fixture_cases

    Raises:
        - OSError if the file cannot be read, ValueError if it is not JSON
    """
    path = path or cu.get_project_root() + PAIRS_PATH
    with open( path, encoding="utf-8" ) as handle:
        document = json.load( handle )
    return { case[ "kind" ]: case for case in document[ "fixture_cases" ] }


def capture_case( case, model, complete=model_transport.complete_sync ):
    """
    Judge one case and keep what was sent and what came back.

    Requires:
        - case has id, kind, actual_text (a string or None) and matching_text, altered_text or both
        - model is a model id; complete has model_transport.complete_sync's signature

    Ensures:
        - returns the fixture: case_id, kind, model, captured_at, actual_text and sides
        - each side the case has holds predicted_text, expected_pass, calls and the judge's verdict
        - calls lists every request the judge made for that side, with its raw reply, in order
        - a verdict that disagrees with expected_pass is recorded as it is, never corrected

    Raises:
        - whatever the judge or the transport raises
    """
    calls = []

    def recording( model_id, system_prompt, user_prompt, **options ):
        reply = complete( model_id, system_prompt, user_prompt, **options )
        calls.append( { "model": model_id, "system_prompt": system_prompt, "user_prompt": user_prompt, "raw_reply": reply } )
        return reply

    judge = make_judge( model, complete=recording )
    sides = {}
    for side, key, expected_pass in SIDES:
        if key not in case: continue
        calls.clear()
        verdict       = judge( case[ key ], case[ "actual_text" ] )
        sides[ side ] = { "predicted_text": case[ key ], "expected_pass": expected_pass, "calls": list( calls ), "verdict": dict( verdict ) }
    captured_at = datetime.datetime.now( datetime.timezone.utc ).isoformat( timespec="seconds" )
    return { "case_id": case[ "id" ], "kind": case[ "kind" ], "model": model, "captured_at": captured_at, "actual_text": case[ "actual_text" ], "sides": sides }


def replay_complete( fixture ):
    """
    Build a transport that answers from one fixture's recorded calls.

    Requires:
        - fixture is a dictionary capture_case returned

    Ensures:
        - returns a callable with complete_sync's signature
        - it returns the recorded raw reply for a recorded model, system prompt and user prompt
        - two user prompts that differ only in their tag suffix are the same request

    Raises:
        - the callable raises KeyError for a request the fixture does not hold
    """
    replies = {
        _request_key( call[ "model" ], call[ "system_prompt" ], call[ "user_prompt" ] ): call[ "raw_reply" ]
        for side in fixture[ "sides" ].values() for call in side[ "calls" ]
    }

    def replay( model_id, system_prompt, user_prompt, **options ):
        key = _request_key( model_id, system_prompt, user_prompt )
        if key not in replies: raise KeyError( f"no recorded reply in fixture {fixture[ 'case_id' ]}: capture it again" )
        return replies[ key ]

    return replay


def main( argv=None, complete=model_transport.complete_sync ):
    """
    Capture one fixture per kind and write each to its own file.

    Requires:
        - argv may hold --model, defaulting to the configured judge model, --out and one or more --kind

    Ensures:
        - writes <out>/<kind>.json for each chosen kind, out defaulting to the committed fixture folder
        - prints one line per side with the expected and the judged pass
        - returns 0 when every side was judged as expected, 1 otherwise

    Raises:
        - SystemExit for bad arguments, KeyError for an unknown --kind
    """
    parser = argparse.ArgumentParser( description="Capture real judge replies into fixtures." )
    parser.add_argument( "--model", default=None, help="model id the judge calls" )
    parser.add_argument( "--out", default=None, help="folder to write into" )
    parser.add_argument( "--kind", action="append", help="capture only this kind; repeatable" )
    args  = parser.parse_args( argv )
    model = args.model or judge_model()
    out   = args.out or cu.get_project_root() + FIXTURE_DIR
    cases = load_cases()
    os.makedirs( out, exist_ok=True )
    missed = 0
    for kind in args.kind or list( cases ):
        fixture = capture_case( cases[ kind ], model, complete=complete )
        with open( os.path.join( out, kind + ".json" ), "w", encoding="utf-8" ) as handle:
            handle.write( json.dumps( fixture, indent=2, ensure_ascii=False ) + "\n" )
        for side, record in fixture[ "sides" ].items():
            verdict = record[ "verdict" ]
            passed  = bool( verdict[ "keeps_every_restriction" ] ) and bool( verdict[ "invents_nothing" ] )
            missed += passed != record[ "expected_pass" ]
            print( f"{kind} {side}: expected pass={record[ 'expected_pass' ]} judged pass={passed}" )
    return 1 if missed else 0


if __name__ == "__main__":
    raise SystemExit( main() )
