"""
The record of podcast proxy cards that have started their one job.

The card id is the primary key, so the database decides who wins when two starts arrive together.
The caller commits between the claim and the queueing, so the second start sees the claim.
"""

import uuid
from typing import Optional

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from cosa.rest.db.repositories.base import BaseRepository
from cosa.rest.postgres_models import PodcastProxySpentCard


class PodcastProxySpentRepository( BaseRepository[ PodcastProxySpentCard ] ):
    """Claim, annotate and release the spent-card record. The caller commits."""

    def __init__( self, session: Session ):
        super().__init__( PodcastProxySpentCard, session )

    def claim( self, card_id: uuid.UUID, started_by: str, scope_path: str, sha256: str ) -> bool:
        """
        Record that this card is starting its job.

        Requires:
            - card_id is the notification id; started_by, scope_path and sha256 come from the stored card

        Ensures:
            - returns True and adds the row when no row has this card id
            - returns False and adds nothing when one does, however many starts raced
            - the row is flushed, so a clash surfaces here and not at the caller's commit
        """
        try:
            with self.session.begin_nested():
                self.session.add( PodcastProxySpentCard( card_id=card_id, started_by=started_by, scope_path=scope_path, sha256=sha256 ) )
            return True
        except IntegrityError:
            return False

    def record_job( self, card_id: uuid.UUID, job_id: Optional[ str ] ) -> None:
        """Set the job id on the card's row. A no-op when the row is gone."""
        row = self.session.get( PodcastProxySpentCard, card_id )
        if row is not None: row.job_id = job_id

    def release( self, card_id: uuid.UUID ) -> bool:
        """
        Take the claim back, so the card can start again.

        Ensures:
            - returns True and deletes the row when one exists; returns False when none does
        """
        row = self.session.get( PodcastProxySpentCard, card_id )
        if row is None: return False
        self.session.delete( row )
        return True

    def is_spent( self, card_id: uuid.UUID ) -> bool:
        """True when a row exists for this card id."""
        return self.session.get( PodcastProxySpentCard, card_id ) is not None
