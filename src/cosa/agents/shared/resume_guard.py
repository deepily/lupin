"""
Resume guard shared by the Test Fix Expediter and the Bug Fix Expediter.

A stalled run saves the ordinal of the phase it was in. A resumed run asks this guard whether
that checkpoint already reached a phase, so it can reuse the stored output instead of redoing the work.
Both agents ask the same function, so they cannot read one ordinal two ways.
"""

from typing import Mapping, Optional


def resume_covers( resume_from_ordinal: Optional[ int ], phase_ordinals: Mapping, phase ) -> bool:
    """
    Say whether a resumed run's checkpoint already reached a phase.

    Requires:
        - phase_ordinals maps each phase of the agent to its ordinal
        - phase is a key of phase_ordinals

    Ensures:
        - returns False when the run is not a resume, so every phase runs
        - returns True when the saved ordinal is at or past the ordinal of the phase
        - returns False for a negative saved ordinal, which marks a checkpoint with no usable phase

    Raises:
        - KeyError if phase is not in phase_ordinals
    """
    if resume_from_ordinal is None: return False
    return resume_from_ordinal >= phase_ordinals[ phase ]
