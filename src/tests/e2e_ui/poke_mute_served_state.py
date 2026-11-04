"""
Pure comparison of the fleet poke switch file with what the server answers.

Kept apart from the Playwright conftest so a unit test can import it.
"""


def assert_served_matches_file( file_state, served, expected_source ):
    """
    Check the server's answer is the file's own record plus the derived source.

    Requires:
        - file_state is what read_poke_mute() returned: muted, set_by, set_at
        - served is the parsed body of GET /api/heartbeat/poke-mute
        - expected_source is "file", "skeleton_crew", "both" or "none"

    Ensures:
        - passes only when served holds the file's three keys with equal values, plus source, and no other key
        - source equals expected_source

    Raises:
        - AssertionError naming both dicts when they differ
    """
    expected = { **file_state, "source": expected_source }
    assert served == expected, ( f"the server's answer must be the file's record plus the source "
                                 f"{expected_source!r}: file={file_state!r} served={served!r}" )
