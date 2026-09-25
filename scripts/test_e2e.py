"""
================================================================================
End-to-End (E2E) Full-Stack Integration Verification Script
CSCI-GA.2630 Assignment 1 Platform

Verifies live networking behavior across the decoupled stack:
1. Spawns a real Uvicorn server on localhost:8000
2. Tests actual live TCP socket connections & HTTP/1.1 negotiation
3. Verifies real Browser CORS Preflight (OPTIONS) from Origin http://localhost:5173
4. Validates full user lifecycle (Register -> Login -> /me -> Update -> Delete)
5. Verifies frontend build bundle in frontend/dist/
================================================================================
"""

import sys
import time
import uuid
import socket
import threading
import uvicorn
import httpx
from pathlib import Path

# Add backend directory to Python module search path
BACKEND_DIR = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from app.main import app

def is_port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('127.0.0.1', port)) == 0

def run_uvicorn_server():
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="warning")

def run_e2e_verification():
    print("==================================================================")
    print("   CSCI-GA.2630 A1: END-TO-END FULL-STACK INTEGRATION TEST        ")
    print("==================================================================")

    # 1. Start live backend server on port 8000
    print("\n[Step 1] Initializing Live Backend Server on http://127.0.0.1:8000...")
    server_thread = threading.Thread(target=run_uvicorn_server, daemon=True)
    server_thread.start()

    # Wait for server to bind and listen
    for _ in range(30):
        if is_port_in_use(8000):
            break
        time.sleep(0.2)
    assert is_port_in_use(8000), "Failed to start live Uvicorn server on port 8000!"
    print("  -> Live Uvicorn server listening on port 8000.")

    client = httpx.Client(base_url="http://127.0.0.1:8000", timeout=10.0)

    # 2. Live Healthcheck
    print("\n[Step 2] Testing Live GET /healthz...")
    health_res = client.get("/healthz")
    assert health_res.status_code == 200
    assert health_res.json() == {"status": "ok"}
    print("  -> PASSED: /healthz responded with 200 OK.")

    # 3. Live CORS Preflight Request from Frontend Origin
    print("\n[Step 3] Testing Live CORS Preflight (OPTIONS) from http://localhost:5173...")
    cors_res = client.options("/api/auth/login", headers={
        "Origin": "http://localhost:5173",
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "Authorization, Content-Type",
    })
    assert cors_res.status_code == 200, f"CORS Preflight failed: {cors_res.status_code}"
    assert "access-control-allow-origin" in cors_res.headers, "Missing Access-Control-Allow-Origin"
    print("  -> PASSED: CORS preflight approved for http://localhost:5173!")

    # 4. Live Grader Account Login
    print("\n[Step 4] Testing Live NYUgrader Account Login...")
    grader_res = client.post("/api/auth/login", json={
        "username": "NYUgrader",
        "password": "Courant2026!"
    })
    assert grader_res.status_code == 200
    grader_token = grader_res.json()["access_token"]
    assert len(grader_token) > 20
    print("  -> PASSED: NYUgrader logged in successfully over real HTTP socket.")

    # 5. Full User Lifecycle over Live Network
    test_uid = uuid.uuid4().hex[:6]
    test_user = f"e2e_{test_uid}"
    print(f"\n[Step 5] Testing Live User Lifecycle for {test_user}...")
    
    # 5a. Register
    reg_res = client.post("/api/auth/register", json={
        "username": test_user,
        "email": f"{test_user}@nyu.edu",
        "password": "SecurePassword123!"
    })
    assert reg_res.status_code == 201
    user_id = reg_res.json()["id"]

    # 5b. Login
    login_res = client.post("/api/auth/login", json={
        "username": test_user,
        "password": "SecurePassword123!"
    })
    assert login_res.status_code == 200
    token = login_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # 5c. GET /me
    me_res = client.get("/api/auth/me", headers=headers)
    assert me_res.status_code == 200
    assert me_res.json()["username"] == test_user

    # 5d. PATCH email
    new_email = f"{test_user}_new@nyu.edu"
    patch_res = client.patch(f"/api/users/{user_id}", headers=headers, json={"email": new_email})
    assert patch_res.status_code == 200
    assert patch_res.json()["email"] == new_email

    # 5e. DELETE account
    del_res = client.delete(f"/api/users/{user_id}", headers=headers)
    assert del_res.status_code == 200

    # 5f. Post-delete token verification (should fail with 401)
    post_del_res = client.get("/api/auth/me", headers=headers)
    assert post_del_res.status_code == 401
    print("  -> PASSED: Full user lifecycle verified over real network socket.")

    # 6. Verify Frontend Production Build Assets
    print("\n[Step 6] Verifying Frontend Production Build Assets...")
    frontend_dist = Path(__file__).resolve().parent.parent / "frontend" / "dist"
    index_html = frontend_dist / "index.html"
    assert index_html.exists(), "frontend/dist/index.html is missing!"
    assert len(list((frontend_dist / "assets").glob("*.js"))) > 0, "No bundled JS files in dist/assets!"
    assert len(list((frontend_dist / "assets").glob("*.css"))) > 0, "No bundled CSS files in dist/assets!"
    print("  -> PASSED: Frontend production bundle (HTML, JS, CSS) verified on disk.")

    print("\n==================================================================")
    print("   ALL E2E INTEGRATION CHECKS PASSED WITH 100% SUCCESS!           ")
    print("==================================================================")

if __name__ == "__main__":
    run_e2e_verification()
