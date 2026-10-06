"""
A submit that was understood and then declined by the job builder.

`SubmitRefused` is raised by a job builder that has a specific, reportable reason not to
produce a job, as opposed to a builder that crashed. The flow reports it as a terminal
`failed` result. Its `route_reason` is the reason, and `submit_details` carries whatever
the builder learned. It exists so a refusal such as "the user cancelled the expeditor
interview" is not flattened into the generic `agentic_build_error` degrade. That degrade
would lose the one fact the caller needs.
"""


class SubmitRefused( Exception ):
    """
    Refusal carrying a reason code, a message and optional details.

    Requires:
        - route_reason is a short snake_case reason
        - message is a human sentence
        - details is a dict of JSON-safe values, or None

    Ensures:
        - carries all three for the flow to report
    """

    def __init__( self, route_reason, message, details=None ):
        super().__init__( message )
        self.route_reason = route_reason
        self.message      = message
        self.details      = details
