from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from .database import engine, Base, SessionLocal
from .models import User
from .auth import hash_password
from .schemas import HealthResponse
from .routes import auth, users

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application Lifespan Event Handler:
    1. Ensures all physical database tables exist upon server startup.
    2. Automatically seeds the course-mandated grading user if not already present:
       - Username: NYUgrader
       - Password: Courant2026!
       - Hashed with 12-round bcrypt to guarantee password security from day 1.
    """
    # Step 1: Ensure database tables are created in the database
    Base.metadata.create_all(bind=engine)
    
    # Step 2: Seed the mandatory NYUgrader grading account
    db: Session = SessionLocal()
    try:
        grader_user = db.query(User).filter(User.username == "NYUgrader").first()
        if not grader_user:
            seeded_grader = User(
                username="NYUgrader",
                email="grader@courant.nyu.edu",
                hashed_password=hash_password("Courant2026!")
            )
            db.add(seeded_grader)
            db.commit()
            print(">>> [SEED] Mandatory grading account 'NYUgrader' verified/created.")
        else:
            print(">>> [SEED] Mandatory grading account 'NYUgrader' already exists.")
    finally:
        db.close()
        
    yield
    # Cleanup actions on shutdown (if any) can be placed here

# Initialize FastAPI Application
app = FastAPI(
    title="FNMS Assignment 1 API",
    description="Foundations and Fundamentals - Secure Authentication and User Management Platform",
    version="1.0.0",
    lifespan=lifespan
)

# -------------------------------------------------------------
# Cross-Origin Resource Sharing (CORS) Middleware
# Required by course: Frontend (port 5173) and Backend (port 8000)
# run on different origins. This middleware handles browser preflight (OPTIONS)
# requests and permits cross-origin API calls with Bearer tokens.
# -------------------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "*"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -------------------------------------------------------------
# Public Health Check Endpoint
# Course Requirement: GET /healthz returns { "status": "ok" } without auth
# -------------------------------------------------------------
@app.get("/healthz", response_model=HealthResponse, tags=["Health"])
def healthz():
    return {"status": "ok"}

# Mount Feature Routers
app.include_router(auth.router)
app.include_router(users.router)
