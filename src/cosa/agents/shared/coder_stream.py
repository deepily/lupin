"""
The loop that reads a Coder's `sdk_query` stream, for both fix expediters.

The bug and test fix expediters hand the Coder a fix prompt and read the stream alike.
They collect its text and note each file it edits.
They tell the user what it is doing and stop on a time-out or a cancel.
"""

from cosa.agents.shared.sdk_error_result import raise_error_result
from cosa.agents.shared.tool_use_summary import summarize_tool_use


async def read_coder_stream( stream, guard, notify, is_cancelled, label, logger, message_types, post_tool_hook ):
    """
    Read a Coder's message stream to its end.

    Requires:
        - stream is the async iterator `sdk_query` returned
        - guard has check_timeout() and check_iteration()
        - notify( text, priority="low" ) is an async function that sends a progress line
        - is_cancelled() returns True once the run is cancelled
        - message_types is ( AssistantMessage, TextBlock, ToolUseBlock, ResultMessage, RateLimitEvent ), the SDK's classes or stand-ins; the caller passes its own module's names so its tests can replace them
        - post_tool_hook( name, input, guard ) is an async function called once for each Edit or Write

    Ensures:
        - returns ( coder_output, files_changed ): the joined, stripped text, and each distinct edited path in first-seen order
        - calls guard.check_timeout() on every message and guard.check_iteration() once at the end
        - stops reading at the first message after is_cancelled() turns True
        - sends one notify line per tool use and one per result message, the result text cut to 200 characters
        - logs a rate-limit event as a warning

    Raises:
        - RuntimeError (through raise_error_result, logged under `label`) when a result message is an error
        - whatever guard.check_timeout() and guard.check_iteration() raise
    """
    assistant_message, text_block, tool_use_block, result_message, rate_limit_event = message_types
    collected_text = []
    files_changed  = []

    async for message in stream:
        guard.check_timeout()

        if is_cancelled():
            break

        if isinstance( message, assistant_message ):
            for block in message.content:
                if isinstance( block, text_block ):
                    collected_text.append( block.text )
                elif isinstance( block, tool_use_block ):
                    if block.name in ( "Edit", "Write" ):
                        file_path = block.input.get( "file_path", "" )
                        if file_path and file_path not in files_changed:
                            files_changed.append( file_path )
                        await post_tool_hook( block.name, block.input, guard )
                    await notify( f"Coder: {summarize_tool_use( block )}", priority="low" )
        elif isinstance( message, text_block ):
            collected_text.append( message.text )
        elif isinstance( message, result_message ):
            if message.is_error: raise_error_result( message, label, logger )
            await notify( getattr( message, "text", str( message ) )[ :200 ], priority="low" )
        elif isinstance( message, rate_limit_event ):
            logger.warning( f"Rate limited: retry_after={getattr( message, 'retry_after', '?' )}s" )

    guard.check_iteration()
    return "".join( collected_text ).strip(), files_changed
