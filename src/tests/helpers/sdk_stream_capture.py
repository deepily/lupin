"""
Save a stream of agent SDK messages as JSON and build the same messages back.

A captured stream comes from one real run of the agent. A test replays it, so the parser under test
reads what the real producer sent and not a stream built by hand.
"""
import dataclasses

import claude_agent_sdk as sdk

TAG = "_class"


def encode( value ):
    """
    Turn an SDK message, or a list of them, into plain JSON data.

    Requires:
        - value holds only SDK dataclasses, lists, dicts and JSON scalars

    Ensures:
        - every dataclass becomes a dict whose _class key names its class
        - decode( encode( value ) ) builds an equal value
    """
    if dataclasses.is_dataclass( value ) and not isinstance( value, type ):
        return { TAG: type( value ).__name__, **{ f.name: encode( getattr( value, f.name ) ) for f in dataclasses.fields( value ) } }
    if isinstance( value, list ): return [ encode( v ) for v in value ]
    if isinstance( value, dict ): return { k: encode( v ) for k, v in value.items() }
    return value


def decode( data ):
    """
    Build SDK messages back from what encode returned.

    Requires:
        - data came from encode, and the named classes exist in claude_agent_sdk

    Ensures:
        - returns dataclass instances for dicts that carry _class, and the plain value otherwise

    Raises:
        - AttributeError when a named class is not in the installed SDK
    """
    if isinstance( data, list ): return [ decode( v ) for v in data ]
    if isinstance( data, dict ):
        fields = { k: decode( v ) for k, v in data.items() if k != TAG }
        return getattr( sdk, data[ TAG ] )( **fields ) if TAG in data else fields
    return data
