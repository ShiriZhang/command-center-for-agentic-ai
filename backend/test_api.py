"""
================================================================================
Automated Test Suite for CSCI-GA.2630 Assignment 1
Simulates the course instructor's automated grading script (PDF Page 5):
1. Exercises all required endpoints:
   - GET /healthz
   - POST /api/auth/register
   - POST /api/auth/login
   - GET /api/auth/me
   - GET /api/users/:id
   - PATCH /api/users/:id
   - DELETE /api/users/:id
2. Validates course seed account (NYUgrader / Courant2026!)
3. Verifies the Three Strict Security Rules:
   - Rule 1: No password hash in any response, error, or payload
   - Rule 2: No token, bad token, or expired token -> 401 (never 200, never 500)
   - Rule 3: Cross-user access (GET, PATCH, DELETE) refused with consistent 403 code
================================================================================
"""

import uuid
from datetime import timedelta
from fastapi.testclient import TestClient
from app.main import app
from app.auth import create_access_token

def assert_no_password_hashes(data, context=""):
    """
    Rule 1 Verification: Recursively checks dictionary/list responses
    to ensure password hashes are never leaked in JSON outputs.
    """
    forbidden_keys = ["password", "hashed_password", "password_hash"]
    if isinstance(data, dict):
        for key, value in data.items():
            for forbidden in forbidden_keys:
                assert forbidden != key.lower(), (
                    f"RULE 1 VIOLATION in {context}: Forbidden key '{key}' found in JSON output!"
                )
            assert_no_password_hashes(value, f"{context}->{key}")
    elif isinstance(data, list):
        for idx, item in enumerate(data):
            assert_no_password_hashes(item, f"{context}[{idx}]")

def run_grading_test_suite():
    print("==================================================================")
    print("   CSCI-GA.2630 ASSIGNMENT 1: AUTOMATED GRADING TEST SUITE        ")
    print("==================================================================")

    with TestClient(app) as client:
        # -------------------------------------------------------------
        # 1. Healthz Endpoint
        # -------------------------------------------------------------
        print("\n[Test 1] Public Healthcheck (GET /healthz)...")
        res_health = client.get("/healthz")
        assert res_health.status_code == 200, f"Expected 200, got {res_health.status_code}"
        assert res_health.json() == {"status": "ok"}, f"Unexpected payload: {res_health.json()}"
        print("  -> PASSED: /healthz returned 200 and {'status': 'ok'}")

        # -------------------------------------------------------------
        # 2. Mandatory NYUgrader Seed Account Login
        # -------------------------------------------------------------
        print("\n[Test 2] Course Grader Account Login (NYUgrader / Courant2026!)...")
        res_grader_login = client.post("/api/auth/login", json={
            "username": "NYUgrader",
            "password": "Courant2026!"
        })
        assert res_grader_login.status_code == 200, f"Grader login failed: {res_grader_login.text}"
        grader_body = res_grader_login.json()
        assert "access_token" in grader_body, "access_token missing in login response"
        assert grader_body.get("token_type") == "bearer", "token_type must be 'bearer'"
        assert_no_password_hashes(grader_body, "NYUgrader Login")
        print("  -> PASSED: NYUgrader successfully logged in, Bearer token received.")

        # -------------------------------------------------------------
        # 3. Register Two Independent Accounts (Alice and Bob)
        # -------------------------------------------------------------
        uid = uuid.uuid4().hex[:6]
        user_a_name = f"alice_{uid}"
        user_b_name = f"bob_{uid}"
        print(f"\n[Test 3] Registering Account A ({user_a_name}) and Account B ({user_b_name})...")

        reg_a = client.post("/api/auth/register", json={
            "username": user_a_name,
            "email": f"{user_a_name}@courant.nyu.edu",
            "password": "PasswordAlice123!"
        })
        assert reg_a.status_code == 201, f"Alice registration failed: {reg_a.text}"
        user_a_data = reg_a.json()
        user_a_id = user_a_data["id"]
        assert_no_password_hashes(user_a_data, "Alice Registration")

        reg_b = client.post("/api/auth/register", json={
            "username": user_b_name,
            "email": f"{user_b_name}@courant.nyu.edu",
            "password": "PasswordBob456!"
        })
        assert reg_b.status_code == 201, f"Bob registration failed: {reg_b.text}"
        user_b_data = reg_b.json()
        user_b_id = user_b_data["id"]
        assert_no_password_hashes(user_b_data, "Bob Registration")
        print(f"  -> PASSED: Created Alice (ID {user_a_id}) and Bob (ID {user_b_id}) without password hashes.")

        # -------------------------------------------------------------
        # 4. Login Both Accounts & Obtain Tokens
        # -------------------------------------------------------------
        print("\n[Test 4] Authenticating Alice and Bob...")
        token_a = client.post("/api/auth/login", json={
            "username": user_a_name,
            "password": "PasswordAlice123!"
        }).json()["access_token"]

        token_b = client.post("/api/auth/login", json={
            "username": user_b_name,
            "password": "PasswordBob456!"
        }).json()["access_token"]
        headers_a = {"Authorization": f"Bearer {token_a}"}
        headers_b = {"Authorization": f"Bearer {token_b}"}
        print("  -> PASSED: Tokens obtained for both accounts.")

        # -------------------------------------------------------------
        # 5. Check GET /api/auth/me for Alice
        # -------------------------------------------------------------
        print("\n[Test 5] Fetching logged-in profile (GET /api/auth/me)...")
        me_res = client.get("/api/auth/me", headers=headers_a)
        assert me_res.status_code == 200, f"/me failed: {me_res.text}"
        assert me_res.json()["username"] == user_a_name
        assert_no_password_hashes(me_res.json(), "/api/auth/me")
        print(f"  -> PASSED: /me correctly identified Alice: {me_res.json()['username']}")

        # -------------------------------------------------------------
        # 6. RULE 2: No token, bad token, or expired token -> 401
        # -------------------------------------------------------------
        print("\n[Test 6] Testing Rule 2 (No token, bad token, expired token -> 401)...")
        # Missing token
        r2_no_token = client.get("/api/auth/me")
        assert r2_no_token.status_code == 401, f"Expected 401 for no token, got {r2_no_token.status_code}"

        # Bad / corrupted token
        r2_bad_token = client.get("/api/auth/me", headers={"Authorization": "Bearer bogus_token_payload_xyz"})
        assert r2_bad_token.status_code == 401, f"Expected 401 for bad token, got {r2_bad_token.status_code}"

        # Expired token
        expired_token = create_access_token({"sub": str(user_a_id)}, expires_delta=timedelta(seconds=-10))
        r2_exp_token = client.get("/api/auth/me", headers={"Authorization": f"Bearer {expired_token}"})
        assert r2_exp_token.status_code == 401, f"Expected 401 for expired token, got {r2_exp_token.status_code}"
        print("  -> PASSED: Rule 2 strictly verified! All invalid tokens returned HTTP 401.")

        # -------------------------------------------------------------
        # 7. RULE 3: Cross-user permission boundaries (The Grader's Focus)
        # Pointing Alice's token at Bob's :id for GET, PATCH, and DELETE
        # All three MUST be refused with the same code (403 Forbidden)!
        # -------------------------------------------------------------
        print("\n[Test 7] Testing Rule 3 (Pointing Alice's token at Bob's :id for GET, PATCH, DELETE)...")
        # Cross GET
        cross_get = client.get(f"/api/users/{user_b_id}", headers=headers_a)
        assert cross_get.status_code == 403, f"Expected 403 on cross GET, got {cross_get.status_code}"

        # Cross PATCH
        cross_patch = client.patch(f"/api/users/{user_b_id}", headers=headers_a, json={"email": "attacker@evil.com"})
        assert cross_patch.status_code == 403, f"Expected 403 on cross PATCH, got {cross_patch.status_code}"

        # Cross DELETE
        cross_delete = client.delete(f"/api/users/{user_b_id}", headers=headers_a)
        assert cross_delete.status_code == 403, f"Expected 403 on cross DELETE, got {cross_delete.status_code}"
        print("  -> PASSED: Rule 3 strictly verified! GET, PATCH, and DELETE all consistently refused with 403.")

        # -------------------------------------------------------------
        # 8. Legitimate Self Account Management (GET, PATCH, DELETE)
        # -------------------------------------------------------------
        print("\n[Test 8] Testing legitimate operations on own account...")
        # Self GET
        self_get = client.get(f"/api/users/{user_a_id}", headers=headers_a)
        assert self_get.status_code == 200
        assert_no_password_hashes(self_get.json(), "Self GET")

        # Self PATCH (update email)
        new_email = f"alice_updated_{uid}@courant.nyu.edu"
        self_patch = client.patch(f"/api/users/{user_a_id}", headers=headers_a, json={"email": new_email})
        assert self_patch.status_code == 200
        assert self_patch.json()["email"] == new_email
        assert_no_password_hashes(self_patch.json(), "Self PATCH")
        print(f"  -> PASSED: Updated Alice's email to {new_email}")

        # Self DELETE (delete account)
        self_del = client.delete(f"/api/users/{user_a_id}", headers=headers_a)
        assert self_del.status_code == 200
        print(f"  -> PASSED: Alice account successfully deleted.")

        # Invalidate deleted user token
        post_del = client.get("/api/auth/me", headers=headers_a)
        assert post_del.status_code == 401, f"Deleted user token should return 401, got {post_del.status_code}"
        print("  -> PASSED: Deleted user token immediately revoked (401).")

    print("\n==================================================================")
    print("   CONGRATULATIONS! ALL BACKEND TESTS PASSED WITH 100% SUCCESS!   ")
    print("==================================================================")

if __name__ == "__main__":
    run_grading_test_suite()
