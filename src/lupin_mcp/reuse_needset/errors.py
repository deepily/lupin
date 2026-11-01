"""
Named errors of the need-set tools.

Each failure carries a code, so a caller reports the cause and never guesses it.
"""

QUOTA_UNFILLABLE        = "QUOTA_UNFILLABLE"
KIND_SPLIT_UNSET        = "KIND_SPLIT_UNSET"
QUOTA_INVALID           = "QUOTA_INVALID"
PLAN_ALREADY_WRITTEN    = "PLAN_ALREADY_WRITTEN"
BAD_NEED                = "BAD_NEED"
NEED_LEAKS_KEY          = "NEED_LEAKS_KEY"
CHECKER_EQUALS_DRAFTER  = "CHECKER_EQUALS_DRAFTER"
UNREADABLE_REPLY        = "UNREADABLE_REPLY"
BAD_ITEM                = "BAD_ITEM"
PACKET_LEAK             = "PACKET_LEAK"
BAD_LABEL               = "BAD_LABEL"
KAPPA_UNDEFINED         = "KAPPA_UNDEFINED"
MANIFEST_MISMATCH       = "MANIFEST_MISMATCH"
PROBE_UNREADABLE        = "PROBE_UNREADABLE"
SEED_NOT_VECTORISED     = "SEED_NOT_VECTORISED"
STRIP_FAILED            = "STRIP_FAILED"
BAD_ROUTE               = "BAD_ROUTE"
NOT_LUPIN_TREE          = "NOT_LUPIN_TREE"
RECEIPT_FIELD_ABSENT    = "RECEIPT_FIELD_ABSENT"
FREEZE_INCOMPLETE       = "FREEZE_INCOMPLETE"
VECTORS_NOT_FROM_INDEX  = "VECTORS_NOT_FROM_INDEX"
FROZEN_COPY_EXISTS      = "FROZEN_COPY_EXISTS"
INDEX_DIFFERS           = "INDEX_DIFFERS"
KEY_REJECTED            = "KEY_REJECTED"
VECTORS_DIFFER          = "VECTORS_DIFFER"
REVALIDATION_OPEN       = "REVALIDATION_OPEN"
CONTROL_INPUT_CHANGED   = "CONTROL_INPUT_CHANGED"
CONTROL_ID_COLLIDES     = "CONTROL_ID_COLLIDES"
CONTROL_NOT_RESTORED    = "CONTROL_NOT_RESTORED"
CALL_CAP_REACHED        = "CALL_CAP_REACHED"
CAP_NOT_INSTALLED       = "CAP_NOT_INSTALLED"
STAGE_BUDGET_REACHED    = "STAGE_BUDGET_REACHED"
SEED_IS_TARGET          = "SEED_IS_TARGET"
SEED_IN_KEY             = "SEED_IN_KEY"
CONTROL_NEED_UNDRAFTED  = "CONTROL_NEED_UNDRAFTED"
STAGE_NOT_WIRED         = "STAGE_NOT_WIRED"
NO_CANDIDATE_STAGE      = "NO_CANDIDATE_STAGE"
NO_CLI_PATH             = "NO_CLI_PATH"
ALL_SEEDS_UNREADABLE    = "ALL_SEEDS_UNREADABLE"
NO_NEEDS_WITH_SKIPS     = "NO_NEEDS_WITH_SKIPS"
SOURCE_EXPORT_FAILED    = "SOURCE_EXPORT_FAILED"
SOURCE_EXPORT_MISMATCH  = "SOURCE_EXPORT_MISMATCH"


class NeedsetError( Exception ):
    """
    A need-set failure with a stable code.

    Requires:
        - code is one of the constants of this module

    Ensures:
        - str( exc ) is the code, followed by ": <detail>" when a detail is given
        - code and detail are kept as attributes
    """

    def __init__( self, code, detail="" ):
        """
        Build the error from a code and an optional detail.

        Ensures:
            - the message starts with the code
        """
        super().__init__( f"{code}: {detail}" if detail else code )
        self.code   = code
        self.detail = detail
