"""
Field checks shared by the xml_models files.

xmltodict parses an empty tag such as <reasoning></reasoning> as None, and a pydantic str field rejects None.
Two checks recur across the agents' response models: turn that None into an empty string, and refuse a field
that came back empty. Each model keeps its own pydantic validator method and calls these for the body.

Usage:
    from cosa.agents.io_models.field_validators import none_to_empty, require_nonempty
"""


def none_to_empty( v, field_name=None, keep_none=() ):
    """
    Turn the None that an empty XML tag parses to into an empty string.

    Requires:
        - keep_none is a tuple of field names that must stay None, such as a required field

    Ensures:
        - returns "" when v is None and field_name is not in keep_none
        - returns v unchanged otherwise
    """
    if v is None and field_name not in keep_none: return ""
    return v


def require_nonempty( v, message, strip=True ):
    """
    Refuse a field that is None, empty or only whitespace.

    Requires:
        - v is a string or None; message is the error text for the refusal

    Ensures:
        - returns v stripped of surrounding whitespace, or v itself when strip is False

    Raises:
        - ValueError with message when v is None, empty or only whitespace
    """
    if v is None or not v.strip(): raise ValueError( message )
    return v.strip() if strip else v
