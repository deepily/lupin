/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// Multiplexer — JWT claim decoding (client-side, no signature verification).
//
// Introduced by the WP0/WP1 token-key migration: the multiplexer now reads the
// canonical cross-client `lupin_access_token` / `lupin_refresh_token` keys,
// which hold RAW JWT strings (not the old schema-versioned `auth_token` blob).
// Expiry is therefore derived from the access-token `exp` claim, and the
// current-user email from the `email` claim (see jwt_service.create_access_token
// in src/cosa/rest/jwt_service.py — claims: sub, email, roles, exp, iat, jti).
//
// SECURITY: this decodes the payload WITHOUT verifying the signature. It is safe
// ONLY for reading non-authoritative client hints (display email, expiry hint).
// The server remains the sole authority on token validity.

export interface JwtClaims {
  exp?   : number;   // expiry — seconds since epoch (RFC 7519)
  email? : string;   // Lupin access-token email claim
  [claim: string]: unknown;
}

// Decode one base64url segment to a UTF-8 string. Returns null on any malformed
// input (invalid base64 length or non-base64 characters).
function decodeSegment( segment: string ): string | null {
  const base64    = segment.replace( /-/g, "+" ).replace( /_/g, "/" );
  const remainder = base64.length % 4;
  if ( remainder === 1 ) return null;   // not a valid base64 length
  const padded = remainder === 0 ? base64 : base64 + "=".repeat( 4 - remainder );
  let binary: string;
  try {
    binary = atob( padded );
  } catch {
    return null;                        // non-base64 characters
  }
  const bytes = Uint8Array.from( binary, ( ch ) => ch.charCodeAt( 0 ) );
  return new TextDecoder().decode( bytes );
}

// Decode the claims payload (second segment) of a JWT. Returns null when the
// token is not a well-formed three-segment JWT, the payload is not decodable,
// or the payload is not a JSON object.
export function decodeJwtClaims( token: string ): JwtClaims | null {
  const segments = token.split( "." );
  if ( segments.length !== 3 ) return null;
  const json = decodeSegment( segments[ 1 ] as string );
  if ( json === null ) return null;
  let parsed: unknown;
  try {
    parsed = JSON.parse( json );
  } catch {
    return null;
  }
  if ( typeof parsed !== "object" || parsed === null ) return null;
  return parsed as JwtClaims;
}

// Access-token expiry as ms-epoch, or null if absent/malformed.
export function jwtExpiryMs( token: string ): number | null {
  const claims = decodeJwtClaims( token );
  if ( claims === null ) return null;
  if ( typeof claims.exp !== "number" ) return null;
  return claims.exp * 1000;
}

// Email claim, or null if absent/empty/malformed.
/* c8 ignore next */ // tsx phantom-branch artifact on function declaration line.
export function jwtEmail( token: string ): string | null {
  const claims = decodeJwtClaims( token );
  if ( claims === null ) return null;
  if ( typeof claims.email !== "string" || claims.email === "" ) return null;
  return claims.email;
}
