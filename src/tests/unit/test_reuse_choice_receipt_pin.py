"""
The three-way question's receipt does not move when the new question is added.

Cheech's condition on unit 7. A fixed fake input is run through the packed path and the old path.
The canonical bytes of each receipt are hashed and the hash is a literal taken before the change.
"""
import pytest

from cosa.repo.symindex import verdict as vd
from lupin_mcp import reuse_tools as rt
from tests.unit.test_reuse_pack_route import PackedFake, env, no_jev_key, packed_ctx, receipt_of      # noqa: F401  (fixtures)
from tests.unit.test_reuse_tools import FEEDS_TEXT, FakeJev
from tests.unit.test_reuse_page_first import HIT

NEED    = "read an RSS feed [pin]"
BEFORE_LANGUAGE = { "packed": "db99d078ad9ffe612a9e33ab20c476cfa99d26da", "old": "b661799dbcd432ece5afa9c1c8f2a9b5788d105b" }      # taken when index_sha began to derive from search_sha (step S3); first taken at db8e910eb, before unit 5
PINNED          = { "packed": "b61a9d067d908b76a7957160425b24ef3b28565b", "old": "2e85e70a4bba8a48b1bf8d370c71c322602a0bd3" }      # re-taken when the receipt gained its `language` field (step 1.4)


@pytest.fixture( autouse=True )
def policy_at_the_pinned_cut( monkeypatch ):
    """Pins the threshold at 0.5 and drops `no_new`, the policy the literals below were taken at.

    Ensures:
        - the receipt carries the policy, so the shipped 0.3 and the `no_new` key would each move both hashes
    """
    monkeypatch.setitem( vd.POLICY, "threshold", 0.5 )
    monkeypatch.delitem( vd.POLICY, "no_new" )                       # the retirement of NEW (24 October) adds this key; the literals are the bytes of a receipt written before it


def receipt_sha( rec ): return rt.sha( rt.canonical( rec ), 40 )


def without_language( rec ):
    """Return the receipt as it was before the language field was added."""
    old = { k: v for k, v in rec.items() if k != "language" }
    old[ "id" ] = rt.receipt_id( rec[ "tool" ], rec[ "query" ], rec[ "index_sha" ], rec[ "model" ], rec[ "policy" ], rec[ "prompt_template_hash" ], rec[ "causes" ],
                                 rec[ "tool_version" ], rec[ "request_shape" ] if "request_shape" in rec else None )
    return old


def test_the_packed_choice_receipt_is_the_one_pinned_before_the_new_question( env ):
    r = rt.check_exists_impl( NEED, packed_ctx( env, PackedFake( NEED, { FEEDS_TEXT: HIT } ) ), language="all" )
    rec = receipt_of( env, r )
    assert receipt_sha( rec ) == PINNED[ "packed" ]
    assert receipt_sha( without_language( rec ) ) == BEFORE_LANGUAGE[ "packed" ]               # the language key and the id it feeds are the whole difference


def test_the_old_path_receipt_is_the_one_pinned_before_the_new_question( env ):
    r = rt.check_exists_impl( NEED, rt.ReuseContext( env[ 0 ], env[ 1 ], out_dir=env[ 2 ], transport=FakeJev( need=NEED ) ), language="all" )
    rec = receipt_of( env, r )
    assert receipt_sha( rec ) == PINNED[ "old" ]
    assert receipt_sha( without_language( rec ) ) == BEFORE_LANGUAGE[ "old" ]                  # the language key and the id it feeds are the whole difference
