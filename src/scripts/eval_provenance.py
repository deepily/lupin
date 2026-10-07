#!/usr/bin/env python3
"""
Provenance stamp an eval arm attaches to its result, moved out of the paired harness.

Why this file exists:
    `v2_eval` imports `make_provenance` from `paired_eval` at module level, and
    `paired_eval` is on the V1 removal list. The import is top-level, so deleting
    `paired_eval` would break every v2 eval at import time. A delete list built by
    naming v1 files misses what v2 still takes from them. Follow the imports instead.

What is here:
    The field tuple every arm artifact must carry, the stamp builder, and the
    order-independent sample fingerprint. The fingerprint decides whether two arms
    measured the same utterances. All three are pure and none is v1-specific.

The code is moved verbatim, so behaviour cannot change under cover of a relocation.
`paired_eval` re-exports all three, so it and its tests are unchanged until it is deleted.
"""

from __future__ import annotations

import hashlib
from typing import Any, Dict, Optional, Sequence, Tuple


# The provenance-stamp fields every arm artifact must carry. `sample_signature` is the
# load-bearing one: two arms measured the same utterances IFF their signatures match.
# `git_sha` is the load-bearing one for WHICH TREE: it is the sha the arm read back from the
# server it actually measured, so a number is auditable to the code that produced it. It is
# in this tuple — not merely printed — so an absent sha is a MISSING FIELD that refuses the
# pairing, rather than a blank the report renders as if it were fine (row c9b43538).
PROVENANCE_FIELDS = ( "arm", "corpus", "seed", "n_per_command", "sample_signature", "sampled_n", "git_sha" )


# ---------------------------------------------------------------------------
# The sample signature — what actually binds two arms to one measured sample.
# ---------------------------------------------------------------------------
def compute_sample_signature( pairs: Sequence[ Tuple[ str, str ] ] ) -> str:
    """
    A deterministic, order-independent fingerprint of the (utterance, command) pairs.

    Requires:
        - pairs is a sequence of (utterance, expected_command) 2-tuples.

    Ensures:
        - returns the sha256 hex of the sorted, deduplicated pair set, so two arms that
          measured the same utterances (in any order) produce the same signature and
          two arms that measured different utterances cannot collide.
        - binds both the utterance text and its expected command (a unit separator
          between the two keeps "a","bc" distinct from "ab","c").
    """
    encoded = sorted( { f"{utterance}\x1f{command}" for utterance, command in pairs } )
    joined  = "\x1e".join( encoded )
    return hashlib.sha256( joined.encode( "utf-8" ) ).hexdigest()


def make_provenance(
    arm           : str,
    corpus        : str,
    seed          : Optional[ int ],
    n_per_command : Optional[ int ],
    sampled_pairs : Sequence[ Tuple[ str, str ] ],
    git_sha       : str,
) -> Dict[ str, Any ]:
    """
    Build the provenance stamp an arm attaches to its serialized result.

    Requires:
        - arm is "v1" or "v2"; corpus is the corpus name both arms load.
        - seed / n_per_command describe the sampler (None on a limit-based run that
          did not sample — such an arm can never pair with a seeded one).
        - sampled_pairs is the exact (utterance, expected_command) set the arm measured.
        - git_sha is the sha read back from the server this arm measured — never a
          constant and never a guess. It is a required argument rather than an optional one.
          An arm that cannot say which tree it ran on must fail at the stamp, where the
          caller can still fix it. Failing at the report is not acceptable, because a blank
          there looks like a legitimate value.

    Ensures:
        - returns a dict carrying exactly PROVENANCE_FIELDS, with sample_signature
          computed from sampled_pairs and sampled_n = len( sampled_pairs ).
    """
    return {
        "arm"              : arm,
        "corpus"           : corpus,
        "seed"             : seed,
        "n_per_command"    : n_per_command,
        "sample_signature" : compute_sample_signature( sampled_pairs ),
        "sampled_n"        : len( sampled_pairs ),
        "git_sha"          : git_sha,
    }
