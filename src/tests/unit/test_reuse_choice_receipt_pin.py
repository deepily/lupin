"""
The three-way question's receipt does not move when the new question is added.

Cheech's condition on unit 7. A fixed fake input is run through the packed path and the old path.
The canonical bytes of each receipt are hashed and the hash is a literal taken before the change.
"""
import pytest

from lupin_mcp import reuse_tools as rt
from tests.unit.test_reuse_pack_route import PackedFake, env, no_jev_key, packed_ctx, receipt_of      # noqa: F401  (fixtures)
from tests.unit.test_reuse_tools import FEEDS_TEXT, FakeJev
from tests.unit.test_reuse_page_first import HIT

NEED    = "read an RSS feed [pin]"
PINNED  = { "packed": "9f37ab288d110bf280321db3d17d3311b001b2d6", "old": "95d85b4660ba7b851c020d80a4e52c5a3855c8d6" }      # taken at db8e910eb, before unit 5


def receipt_sha( rec ): return rt.sha( rt.canonical( rec ), 40 )


def test_the_packed_choice_receipt_is_the_one_pinned_before_the_new_question( env ):
    r = rt.check_exists_impl( NEED, packed_ctx( env, PackedFake( NEED, { FEEDS_TEXT: HIT } ) ) )
    assert receipt_sha( receipt_of( env, r ) ) == PINNED[ "packed" ]


def test_the_old_path_receipt_is_the_one_pinned_before_the_new_question( env ):
    r = rt.check_exists_impl( NEED, rt.ReuseContext( env[ 0 ], env[ 1 ], out_dir=env[ 2 ], transport=FakeJev( need=NEED ) ) )
    assert receipt_sha( receipt_of( env, r ) ) == PINNED[ "old" ]
