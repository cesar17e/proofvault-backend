# ProofVault authentication contract

ProofVault delegates signup, login, password management, access-token issuance,
refresh-token rotation, and logout to Supabase Auth. The FastAPI backend does
not issue or refresh sessions. It accepts Supabase access tokens through the
`Authorization: Bearer <token>` request header.

## Signing and verification

The Supabase project uses an asymmetric ECC P-256 signing key and the ES256
algorithm. ProofVault will verify access-token signatures with the matching
public key from the project's JWKS endpoint. It will never store or use the
legacy shared JWT secret to verify user tokens.

The following values are derived from `SUPABASE_URL`:

- Issuer: `<SUPABASE_URL>/auth/v1`
- JWKS: `<SUPABASE_URL>/auth/v1/.well-known/jwks.json`

The accepted algorithm is `ES256`, and the accepted audience is
`authenticated`. Both are fixed application settings rather than values
trusted from an unverified token header or payload.

## Accepted user claims

A verified ProofVault user token must contain:

- `iss`: the configured Supabase Auth issuer
- `aud`: the `authenticated` audience
- `exp`: token expiration time
- `iat`: token issue time
- `sub`: the Supabase user UUID
- `role`: `authenticated`
- `aal`: `aal1` or `aal2`
- `session_id`: the Supabase session UUID
- `email` and `phone`: Supabase identity fields, which may be empty
- `is_anonymous`: `false`

The optional `nbf` and `jti` claims are accepted when present. Additional
Supabase claims may be preserved, but they do not grant ProofVault permissions.
The verifier validates claim shape only after it has cryptographically verified
the token signature, issuer, audience, and lifetime.

## Verification failures

The verifier is independent of FastAPI and raises application-domain errors.
Invalid, expired, forged, or untrusted-key tokens raise
`InvalidAccessTokenError`. A connection failure or malformed response from the
configured JWKS endpoint raises `JWKSUnavailableError`. Milestone 2.3 will map
these errors to HTTP responses.

The JWKS client caches the key set for up to ten minutes, uses a five-second
network timeout, and retains PyJWT's cooldown for forced refreshes after an
unknown key ID. It never selects a JWKS URL from token-controlled data.

## Identity and ownership

The verified `sub` UUID is the only source of the application's user identity.
It maps to `owner_id` on ProofVault-owned records and to `auth.users.id` in
Supabase PostgreSQL.

Clients must never choose or override `owner_id`. Future create operations will
set it from the verified user, and every read, update, delete, indexing, and
search operation will be scoped to that same UUID. JWT verification proves
identity; owner-scoped application queries enforce authorization.

## Configuration boundary

The backend requires `SUPABASE_URL`. `SUPABASE_JWT_ALGORITHM` defaults to
`ES256`, and `SUPABASE_JWT_AUDIENCE` defaults to `authenticated`. No Supabase
service-role key or JWT signing secret is required for this contract.

The frontend may use the public Supabase project URL and publishable key. It
must never receive the database connection string, a service-role key, or any
other backend credential.

## Verification status

Automated verification uses locally generated P-256 keys and mocked JWKS
responses. Testing real Supabase access tokens is intentionally deferred to
Milestone 2.4, when `/api/v1/users/me` provides the complete authentication
flow.
