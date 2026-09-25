# auth-foundation Specification

## Purpose
Provides user authentication, credential security, profile management, and network authorization boundaries for the Assignment 1 foundational platform.

## Requirements

### Requirement: System Health Endpoint
The backend SHALL expose a public health check endpoint at `GET /healthz`.

#### Scenario: Health check success
- **WHEN** client sends a `GET` request to `/healthz` without credentials
- **THEN** system responds with HTTP status 200 and JSON body `{"status": "ok"}`

### Requirement: User Registration
The backend SHALL expose `POST /api/auth/register` to register new users with username, email, and password.

#### Scenario: Successful registration
- **WHEN** client sends valid registration JSON with username, email, and password
- **THEN** system hashes password with bcrypt, stores user, responds with HTTP status 201, and returns user profile without password hash

#### Scenario: Duplicate registration rejected
- **WHEN** client attempts registration with an existing username or email
- **THEN** system responds with HTTP status 400 Bad Request

### Requirement: User Login and Token Issuance
The backend SHALL expose `POST /api/auth/login` to authenticate users and return a signed JWT token.

#### Scenario: Successful login
- **WHEN** client submits valid username and password
- **THEN** system responds with HTTP status 200 containing `access_token` and `token_type: "bearer"`

#### Scenario: Invalid login credentials
- **WHEN** client submits non-existent username or incorrect password
- **THEN** system responds with HTTP status 401 Unauthorized

### Requirement: Authenticated Current User Profile
The backend SHALL expose `GET /api/auth/me` to retrieve the currently authenticated user's profile.

#### Scenario: Retrieve current user profile
- **WHEN** client sends `GET /api/auth/me` with header `Authorization: Bearer <valid-token>`
- **THEN** system responds with HTTP status 200 and the user's id, username, and email

### Requirement: Security Rule 1 - No Password Hash Exposure
The system SHALL NEVER return password hashes from any endpoint, error message, or response payload.

#### Scenario: Verify response sanitize
- **WHEN** client inspects responses from register, login, profile, or user endpoints
- **THEN** the JSON payload contains no `password`, `hashed_password`, or `password_hash` fields

### Requirement: Security Rule 2 - Strict 401 on Invalid Credentials
The system SHALL reject requests lacking valid credentials with HTTP status 401 Unauthorized, never 200 or 500.

#### Scenario: Missing token
- **WHEN** client requests a protected endpoint without an Authorization header
- **THEN** system responds with HTTP status 401 Unauthorized

#### Scenario: Malformed or expired token
- **WHEN** client requests a protected endpoint with an invalid, forged, or expired token
- **THEN** system responds with HTTP status 401 Unauthorized

### Requirement: Security Rule 3 - Cross-User Authorization Boundary
The system SHALL prevent users from reading, modifying, or deleting other users' accounts, consistently returning HTTP status 403 Forbidden.

#### Scenario: Cross-user GET rejected
- **WHEN** authenticated User A requests `GET /api/users/{user_b_id}`
- **THEN** system responds with HTTP status 403 Forbidden

#### Scenario: Cross-user PATCH rejected
- **WHEN** authenticated User A requests `PATCH /api/users/{user_b_id}`
- **THEN** system responds with HTTP status 403 Forbidden

#### Scenario: Cross-user DELETE rejected
- **WHEN** authenticated User A requests `DELETE /api/users/{user_b_id}`
- **THEN** system responds with HTTP status 403 Forbidden

### Requirement: Self User Account Management
The system SHALL allow an authenticated user to view, update, and delete their own account.

#### Scenario: Self profile read
- **WHEN** authenticated User A requests `GET /api/users/{user_a_id}`
- **THEN** system responds with HTTP status 200 and User A profile

#### Scenario: Self profile update
- **WHEN** authenticated User A requests `PATCH /api/users/{user_a_id}` with updated email or password
- **THEN** system updates database record and responds with HTTP status 200

#### Scenario: Self account deletion
- **WHEN** authenticated User A requests `DELETE /api/users/{user_a_id}`
- **THEN** system deletes user record, invalidates future requests, and responds with HTTP status 200

### Requirement: Mandatory Grader Seed Account
The system SHALL automatically seed the designated grading user upon server startup.

#### Scenario: Grader login ready
- **WHEN** client logs in with username `NYUgrader` and password `Courant2026!`
- **THEN** system authenticates successfully and issues a valid JWT token

### Requirement: Dedicated Frontend Screens
The frontend SHALL provide 4 dedicated user interfaces: Register, Login, Home, and Account.

#### Scenario: View navigation
- **WHEN** user interacts with the frontend application
- **THEN** unauthenticated users can access Register and Login, and authenticated users can access Home (Command Center) and Account management
