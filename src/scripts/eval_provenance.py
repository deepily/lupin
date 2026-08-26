#!/usr/bin/env python3
"""
The provenance stamp an eval arm attaches to its result — moved out of the paired harness.

WHY THIS FILE EXISTS, AND WHY IT IS URGENT. `v2_eval` imports `make_provenance` from
`paired_eval` **at module level** (`from paired_eval import make_provenance`), and
`paired_eval` is on the V1 excision's delete list (row e2099400 §2). Not a lazy import
inside a function — a top-level one, so the deletion would not have degraded v2's numbers,
it would have killed every v2 eval at import time.

⚠️ THIS IS THE SECOND DEPENDENCY OF EXACTLY THE SHAPE MARÍA FOUND, and it was not in the
plan's blast radius either. Hers (§6.1) was `load_mappable_commands` reaching into
`v1_eval_arm` for the routing denominator. The lesson that generalises: the plan's file
list was assembled by asking *what is v1 apparatus*, and both misses came from the other
direction — *what does v2 still take FROM it*. A delete list built by naming files is not
the same as one built by following imports.

WHAT IS HERE. Three things, all pure: the field tuple every arm artifact must carry, the
order-independent sample fingerprint that decides whether two arms measured the same
utterances, and the stamp builder. None of it is v1-specific — it is the vocabulary of an
eval ARM, and v2 is one.

⚠️ A MOVE, NOT A REWRITE. Verbatim, so behaviour cannot change under cover of a
relocation. `paired_eval` re-exports all three, so it and its tests are unchanged until it
is deleted.

Created: 2026-08-26 (row e2099400 §2 Step 2)
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
        - returns the sha256 hex of the SORTED, DEDUPED pair set, so two arms that
          measured the same utterances (in any order) produce the same signature and
          two arms that measured different utterances cannot collide.
        - binds BOTH the utterance text AND its expected command (a unit separator
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
          did not sample — such an arm can never pair with a seeded one, by design).
        - sampled_pairs is the exact (utterance, expected_command) set the arm measured.
        - git_sha is the sha READ BACK from the server this arm measured — never a
          constant and never a guess. It is a REQUIRED argument rather than an optional
          one on purpose: an arm that cannot say which tree it ran on must fail at the
          stamp, where the caller can still fix it, and not at the report, where a blank
          is indistinguishable from a legitimate one (row c9b43538).

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
