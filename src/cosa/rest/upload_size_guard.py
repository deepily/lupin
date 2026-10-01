#!/usr/bin/env python3
"""
Reject an oversized /api/docs/upload BEFORE its body is read, then count the streamed bytes.

Why this exists (row from Mr. Radio, 2026-09-30): the 100 MB cap in `docs_files.upload_docs_file`
is checked inside the handler's chunk loop. By the time that loop runs, FastAPI has already parsed
the multipart body and spooled all of it to a temp file, and the handler then copies it to a second
one. A 5 GB request therefore costs ~10 GB of disk before the 413. A dependency cannot fix it
either: FastAPI reads the body before it solves dependencies.

Two checks, because Content-Length alone is a claim the client can omit (chunked) or understate:
  1. a declared Content-Length over the limit is refused at once, without reading a byte;
  2. otherwise every body chunk is counted as it streams in, and the request is aborted with 413
     the moment the total passes the limit.

The limit is the file cap plus a small slack for multipart framing and the form fields. The exact
per-file check in the handler stays as the backstop.
"""
import json

# Multipart boundaries, the `dir` and `on_conflict` fields and per-part headers. A request at the cap
# carries a little more than the cap; this stops that being refused here while the handler would admit it.
FRAMING_SLACK_BYTES = 1024 * 1024
GUARDED_PATH        = "/api/docs/upload"
GUARDED_METHOD      = "POST"


class _BodyTooLarge( Exception ):
    """Raised inside the wrapped receive() to stop the application reading further."""


def _cap_bytes() -> int:
    """The handler's own cap, read at CALL time so a test (or an operator) can change it."""
    from cosa.rest.routers import docs_files
    return docs_files.UPLOAD_MAX_BYTES


class UploadSizeGuard:
    """
    ASGI middleware, scoped to POST /api/docs/upload and nothing else.

    Requires:
        - app is an ASGI application
    Ensures:
        - any other path, method or scope type passes through untouched
        - a Content-Length over cap + slack answers 413 without the body being read
        - a non-numeric or negative Content-Length answers 400
        - a body with no (or a false) Content-Length is counted as it streams, and the request is
          answered 413 once the count passes cap + slack, whatever the application tries to say
        - a body within the limit reaches the application unchanged
    """

    def __init__( self, app, cap_fn=_cap_bytes ):
        self.app    = app
        self.cap_fn = cap_fn

    async def __call__( self, scope, receive, send ):
        if scope[ "type" ] != "http" or scope[ "method" ] != GUARDED_METHOD or scope[ "path" ] != GUARDED_PATH:
            await self.app( scope, receive, send )
            return

        limit    = self.cap_fn() + FRAMING_SLACK_BYTES
        declared = dict( scope[ "headers" ] ).get( b"content-length" )
        if declared is not None:
            try:
                declared_bytes = int( declared )
            except ValueError:
                declared_bytes = -1
            if declared_bytes < 0:
                await self._reject( send, 400, "Content-Length must be a non-negative integer" )
                return
            if declared_bytes > limit:
                await self._reject( send, 413, self._too_large( limit ) )
                return

        state = { "received": 0, "tripped": False, "answered": False }

        async def counted_receive():
            message = await receive()
            if message[ "type" ] == "http.request":
                state[ "received" ] += len( message.get( "body", b"" ) )
                if state[ "received" ] > limit:
                    state[ "tripped" ] = True
                    raise _BodyTooLarge()
            return message

        async def guarded_send( message ):
            if not state[ "tripped" ]:
                await send( message )
            elif not state[ "answered" ]:
                # The application is replying to a body we cut short (FastAPI turns the abort into a
                # 400): put the truth in its place, once, and drop the rest of what it says.
                state[ "answered" ] = True
                await self._reject( send, 413, self._too_large( limit ) )

        try:
            await self.app( scope, counted_receive, guarded_send )
        except _BodyTooLarge:
            pass
        if state[ "tripped" ] and not state[ "answered" ]:
            await self._reject( send, 413, self._too_large( limit ) )

    @staticmethod
    def _too_large( limit ) -> str:
        return f"Upload body exceeds the {( limit - FRAMING_SLACK_BYTES ) // ( 1024 * 1024 )} MB upload cap"

    @staticmethod
    async def _reject( send, status, detail ):
        body = json.dumps( { "detail": detail } ).encode()
        await send( { "type": "http.response.start", "status": status,
                      "headers": [ ( b"content-type", b"application/json" ),
                                   ( b"content-length", str( len( body ) ).encode() ),
                                   ( b"connection", b"close" ) ] } )
        await send( { "type": "http.response.body", "body": body } )
