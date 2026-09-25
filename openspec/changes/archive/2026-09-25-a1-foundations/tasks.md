# Tasks: Assignment 1 Implementation Plan

## 1. Project Scaffolding & Environment Setup

- [x] 1.1 Create root `.gitignore` to block secret leakage and verify `.env` files are ignored
- [x] 1.2 Create `backend/requirements.txt` with required dependencies and initialize virtual environment
- [x] 1.3 Create backend `.env.example`, `.env`, and `app/config.py` for configuration loading

## 2. Database & Data Modeling

- [x] 2.1 Implement SQLAlchemy database engine and session dependency in `app/database.py`
- [x] 2.2 Define `User` database table model in `app/models.py`
- [x] 2.3 Define Pydantic request/response schemas in `app/schemas.py` enforcing Rule 1 (no password hash)

## 3. Cryptography & Security Core

- [x] 3.1 Implement bcrypt password hashing and verification in `app/auth.py`
- [x] 3.2 Implement JWT token generation and authentication dependency in `app/auth.py` enforcing Rule 2 (401 on invalid/missing token)

## 4. Backend API Endpoints & Authorization Rules

- [x] 4.1 Implement `POST /api/auth/register`, `POST /api/auth/login`, and `GET /api/auth/me` in `app/routes/auth.py`
- [x] 4.2 Implement `GET /api/users/:id`, `PATCH /api/users/:id`, and `DELETE /api/users/:id` in `app/routes/users.py` enforcing Rule 3 (403 on cross-user access)
- [x] 4.3 Assemble `app/main.py` with `GET /healthz`, CORS middleware, and automatic startup seeding of `NYUgrader` account
- [x] 4.4 Create automated test suite `backend/test_api.py` and verify all endpoints, security rules, and grader accounts pass

## 5. Frontend Application Development

- [x] 5.1 Initialize Vite + React project in `frontend/` and configure Tailwind CSS
- [x] 5.2 Create API service client and Auth Context to manage JWT tokens and authenticated session state
- [x] 5.3 Implement Register and Login screen views
- [x] 5.4 Implement Home screen view (signed-in empty room command center)
- [x] 5.5 Implement Account management screen view (update email/password, delete account)

## 6. Verification & Final Documentation

- [x] 6.1 Conduct end-to-end full-stack integration test between frontend and backend
- [x] 6.2 Write course-compliant `README.md` and Assignment Journal draft based on OpenSpec design decisions
