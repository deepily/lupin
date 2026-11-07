"""Adversarial real-git probes of at_risk_work (review of 66729046c)."""
import cosa.agents.shared.worktree_reaper as wr
from tests.unit.test_the_janitor_evacuates_and_archives import (
    repo, pushed, _out, _commit, _tree, NOW, _no_live_spawn_registry,
)


def test_a_pushed_line_that_never_reached_the_target_is_not_landed( pushed ):
    """Never squashed or merged: the commits sit only on origin/old-line, not on the target."""
    outcome = wr.retire_branch( str( pushed ), "old-line", "wip-v9", now=NOW )
    assert outcome[ "landed" ] is False


def test_the_squash_test_does_not_need_the_squash( pushed ):
    """The squash changes nothing: the answer is the same with and without it."""
    with_no_squash = wr.at_risk_work( str( pushed ), "old-line", "wip-v9", wr._default_run )
    _out( pushed, "merge", "--squash", "old-line" )
    _out( pushed, "commit", "-q", "-m", "squash of old-line" )
    with_squash = wr.at_risk_work( str( pushed ), "old-line", "wip-v9", wr._default_run )
    assert with_no_squash == with_squash
