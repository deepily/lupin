"""
Census guard: no stance is split out of an answer anywhere but the one parser.

Scope is the three modules the Preference learning plan named: the prediction engine,
the accuracy comparators and the podcast proxy. Other `startswith( "yes" )` tests exist
elsewhere in the tree. They sit outside this guard and are listed in `OUTSIDE_THE_SCOPE`.
So the denominator is stated, not implied.

Two detectors, because the stance split has two shapes. The first finds a
`startswith` of a stance word. The second finds a split on the comment marker, which is
how `podcast_proxy.answer_word` once read the word, and which a `startswith` search cannot see.
"""

import re

import cosa.utils.util as cu

SCOPE = (
    "/src/cosa/agents/prediction_engine/prediction_engine.py",
    "/src/cosa/agents/prediction_engine/accuracy_comparators.py",
    "/src/cosa/rest/podcast_proxy.py",
)

OUTSIDE_THE_SCOPE = (
    "src/cosa/agents/runtime_argument_expeditor/expeditor.py",
    "src/cosa/rest/task_promotion_gate.py",
    "src/cosa/agents/utils/agent_notification_dispatcher.py",
    "src/cosa/agents/test_fix_expediter/orchestrator.py",
    "src/lupin_mcp/self_respin_core.py",
    "src/cosa/crud_for_dataframes/agent.py",
    "src/lupin_mcp/podcast_for_rick.py",
)

STARTSWITH_STANCE = re.compile( r"""startswith\(\s*["'](yes|no|neither)""", re.IGNORECASE )
COMMENT_MARKER_SPLIT = re.compile( r"""\.(split|rsplit|partition|find|index)\(\s*(COMMENT_MARKER|["']\[comment:)""", re.IGNORECASE )


def stance_splits( source ):
    """
    Every line of `source` that splits a stance out of an answer by hand.

    Requires:
        - source is Python source text

    Ensures:
        - returns the ( line number, line ) pairs matching either detector
        - a split on the comment marker is a method call, so prose quoting the marker is not reported
    """
    return [ ( number, line.strip() ) for number, line in enumerate( source.splitlines(), 1 )
             if STARTSWITH_STANCE.search( line ) or COMMENT_MARKER_SPLIT.search( line ) ]


def _read( relative_path ):
    with open( cu.get_project_root() + relative_path ) as handle:
        return handle.read()


def test_the_detectors_find_each_shape_of_split():
    """Positive control: both detectors report a planted split, so a zero below means something."""
    planted = 'a = x.lower().startswith( "yes" )\nb = v.split( COMMENT_MARKER, 1 )\nc = v.find( "[comment:" )\n'
    assert [ number for number, _ in stance_splits( planted ) ] == [ 1, 2, 3 ]
    assert stance_splits( "word = extract_qualifier_comment( v )[ 0 ]\n" ) == []


def test_every_stance_split_goes_through_the_parser():
    """No module in scope splits a stance by hand, and each one imports the parser."""
    found = { path: stance_splits( _read( path ) ) for path in SCOPE }
    assert len( found ) == 3
    assert found == { path: [] for path in SCOPE }
    for path in SCOPE:
        assert "extract_qualifier_comment" in _read( path ), path


def test_the_modules_outside_the_scope_are_named_and_exist():
    """The denominator: each listed file exists, so the list cannot rot into a lie."""
    for relative in OUTSIDE_THE_SCOPE:
        assert len( _read( "/" + relative ) ) > 0, relative
