# Proposal: Assignment 1 - Foundations and Fundamentals

## Why
Assignment 1 establishes the foundational command center and secure full-stack baseline for the FNMS course and the upcoming Agentic Tracker in A2. This change builds a secure, persistent, and decoupled web application with robust authentication, cross-origin networking capabilities, and strict authorization boundaries.

## What Changes
- Initialize root Git ignore patterns to protect secrets (`.env`) from repository exposure.
- Implement a Python FastAPI backend providing RESTful endpoints for health checking, registration, JWT login, profile fetching, and account modification/deletion.
- Integrate SQLAlchemy ORM with support for persistent storage (Cloud PostgreSQL e.g., Neon, with local SQLite compatibility).
- Implement password hashing using bcrypt (OWASP compliant, 12 salt rounds) and Bearer token JWT authentication.
- Enforce the Three Strict Security Rules:
  1. Never return password hashes under any circumstance.
  2. Missing, invalid, or expired tokens consistently return HTTP 401.
  3. Cross-user operations on `/api/users/:id` consistently return HTTP 403 Forbidden.
- Pre-seed the required grading user: `NYUgrader` / `Courant2026!`.
- Configure CORS middleware on the backend to support cross-origin requests from the frontend.
- Build a responsive React + Vite + Tailwind CSS frontend featuring 4 dedicated screens: Register, Login, Home (Command Center empty room), and Account management.
- Provide automated verification scripts and clear README documentation.

## Capabilities

### New Capabilities
- `auth-foundation`: Covers user registration, bcrypt password hashing, JWT authentication, user lifecycle management (GET/PATCH/DELETE), cross-origin network policies, and the three mandatory security invariants.

### Modified Capabilities
<!-- None, initial foundation -->

## Impact
- **Backend**: New FastAPI application in `backend/` with SQLAlchemy database engine and JWT auth dependencies.
- **Frontend**: New React + Vite single-page application in `frontend/` styled with Tailwind CSS.
- **Environment**: Requires Python 3.11+ and Node.js 20+.
