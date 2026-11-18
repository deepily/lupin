"""
The loop that reads a Tester stream and judges the fix, for both fix expediters.

The bug and test fix expediters hand the Tester a verification prompt and read the stream alike.
They collect its text, note each test file it writes, and then run the first of those files themselves.
Their own run overrides the Tester's word.
"""

from cosa.agents.shared.sdk_error_result import raise_error_result


async def verify_with_tester( open_stream, guard, notify, label, logger, message_types, post_tool_hook, run_pytest, reraise, debug=False, error_label=None ):
    """
    Read a Tester's message stream and decide whether the fix passed.

    Requires:
        - open_stream() returns the async iterator `sdk_query` returned; it is called inside the guarded block, so a failure to open is caught like a failure to read
        - guard has check_timeout()
        - notify( text, priority="low" ) is an async function that sends a progress line
        - message_types is ( AssistantMessage, TextBlock, ToolUseBlock, ResultMessage, RateLimitEvent ), the SDK's classes or stand-ins; the caller passes its own module's names so its tests can replace them
        - post_tool_hook( name, input, guard ) is an async function called once for each Edit or Write
        - run_pytest( path, timeout_secs=60 ) is an async function returning an object with passed, passed_count and total_tests
        - reraise is the safety-limit exception class, which the caller owns because the safety primitives are an optional import
        - error_label is None to ignore an error result message, or the label to log one under and fail on
        - debug is a bool

    Ensures:
        - returns ( passed, tester_output ): the Tester's text, joined and stripped, and whether it reports a pass
        - the Tester passes when its text says "pass" and not "fail", or says "all tests pass"
        - the first test file the Tester wrote that ends in .py and has "test" in its name is run with run_pytest, and a failure there turns passed False; no later file is run
        - calls guard.check_timeout() on every message
        - sends one notify line per tool use, and logs a rate-limit event as a warning
        - returns ( False, "Verification error: <the error>" ) and logs `Verification failed` when anything but `reraise` is raised
        - prints the pytest result and the verdict under `label` when debug is true

    Raises:
        - reraise, unchanged
    """
    assistant_message, text_block, tool_use_block, result_message, rate_limit_event = message_types

    try:
        collected_text = []
        test_files     = []

        async for message in open_stream():
            guard.check_timeout()

            if isinstance( message, assistant_message ):
                for block in message.content:
                    if isinstance( block, text_block ):
                        collected_text.append( block.text )
                    elif isinstance( block, tool_use_block ):
                        if block.name in ( "Edit", "Write" ):
                            file_path = block.input.get( "file_path", "" )
                            if file_path and file_path not in test_files:
                                test_files.append( file_path )
                            await post_tool_hook( block.name, block.input, guard )
                        await notify( f"Tester: {block.name}", priority="low" )
            elif isinstance( message, text_block ):
                collected_text.append( message.text )
            elif isinstance( message, result_message ):
                if error_label is not None and message.is_error: raise_error_result( message, error_label, logger )
            elif isinstance( message, rate_limit_event ):
                logger.warning( f"Rate limited: retry_after={getattr( message, 'retry_after', '?' )}s" )

        tester_output = "".join( collected_text ).strip()
        output_lower  = tester_output.lower()

        # Tester self-report
        passed = (
            "pass" in output_lower and "fail" not in output_lower
        ) or "all tests pass" in output_lower

        # Independent pytest validation overrides the Tester's self-report
        for tf in test_files:
            if tf.endswith( ".py" ) and "test" in tf.lower():
                run_result = await run_pytest( tf, timeout_secs=60 )
                if not run_result.passed:
                    passed = False
                if debug: print( f"[{label}] pytest {tf}: {'PASS' if run_result.passed else 'FAIL'} "
                                 f"({run_result.passed_count}/{run_result.total_tests})" )
                break  # Only validate first test file

        if debug: print( f"[{label}] Verification: {'PASS' if passed else 'FAIL'}" )

        return ( passed, tester_output )

    except reraise:
        raise
    except Exception as e:
        logger.error( f"Verification failed: {e}" )
        return ( False, f"Verification error: {e}" )
