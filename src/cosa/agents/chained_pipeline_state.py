#!/usr/bin/env python3
"""
Shared result predicate for the chained Deep Research pipelines.

The Deep Research to Podcast and Deep Research to Presentation pipelines each keep their own
PipelineState enum and ChainedResult dataclass. They share one rule for a half-finished run,
which lives here as a mixin so the two result classes agree on it.
"""


class ChainedResultMixin:
    """
    Predicate shared by the chained pipelines' result dataclasses.

    A subclass sets two class attributes.
    PARTIAL_STATES lists the states under which a run can count as partial.
    PRIMARY_ARTIFACT names the field that stays None when the second stage made nothing.
    """

    PARTIAL_STATES   = ()
    PRIMARY_ARTIFACT = ""

    def is_partial( self ) -> bool:
        """
        Check if the research stage finished but the second stage produced nothing.

        Requires:
            - the subclass sets PARTIAL_STATES and PRIMARY_ARTIFACT
            - self has state and research_path fields, and a field named by PRIMARY_ARTIFACT

        Ensures:
            - Returns True only when state is in PARTIAL_STATES, research_path is set and
              the PRIMARY_ARTIFACT field is None
        """
        return (
            self.state in self.PARTIAL_STATES
            and self.research_path is not None
            and getattr( self, self.PRIMARY_ARTIFACT ) is None
        )
