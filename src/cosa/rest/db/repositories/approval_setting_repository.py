"""
Approval-settings repository — persistence only.

Validation of keys and values lives in `cosa.rest.task_approval_settings`, which calls this
after validating. Every method runs inside the caller's `get_db()` transaction.
"""

from typing import Optional

from cosa.rest.postgres_models import ApprovalSetting
from cosa.rest.db.repositories.base import BaseRepository


class ApprovalSettingRepository( BaseRepository[ApprovalSetting] ):
    """
    Read and upsert approval-setting rows.

    Requires:
        - session is an active SQLAlchemy session
    """

    def __init__( self, session ):
        super().__init__( ApprovalSetting, session )

    def get_all( self ) -> dict:
        """
        Every stored setting.

        Ensures:
            - returns { key: value } for every row, marker rows included
        """
        return { row.key: row.value for row in self.session.query( ApprovalSetting ).all() }

    def has_key( self, key: str ) -> bool:
        """
        Whether a row named `key` exists.
        """
        return self.session.get( ApprovalSetting, key ) is not None

    def upsert_many( self, updates: dict, updated_by: Optional[ str ] ) -> None:
        """
        Write every key in `updates`, replacing any existing value.

        Requires:
            - updates values are JSON-serialisable and already validated

        Ensures:
            - keys not named in `updates` are untouched
            - each written row records `updated_by`
        """
        for key, value in updates.items():
            row = self.session.get( ApprovalSetting, key )
            if row is None:
                self.session.add( ApprovalSetting( key=key, value=value, updated_by=updated_by ) )
            else:
                row.value      = value
                row.updated_by = updated_by
        self.session.flush()
