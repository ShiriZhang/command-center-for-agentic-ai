from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from .config import settings

# -------------------------------------------------------------
# 1. Connection Arguments
# SQLite by default restricts access to the thread that created it.
# In FastAPI's multi-threaded asynchronous environment, we must disable
# this check with check_same_thread=False when using SQLite.
# -------------------------------------------------------------
connect_args = {}
if settings.DATABASE_URL.startswith("sqlite"):
    connect_args["check_same_thread"] = False

# -------------------------------------------------------------
# 2. Database Engine & Connection Pooling
# pool_pre_ping=True: Essential for Serverless Cloud Databases (Neon/Supabase)
# It tests ("pings") the connection before handing it to a request.
# If an idle cloud connection was suspended or dropped by the remote firewall,
# SQLAlchemy automatically re-establishes a fresh connection seamlessly.
# -------------------------------------------------------------
engine = create_engine(
    settings.DATABASE_URL,
    connect_args=connect_args,
    pool_pre_ping=True
)

# -------------------------------------------------------------
# 3. Session Factory (SessionLocal)
# Produces database sessions with explicit transaction boundaries:
# autocommit=False ensures transactions are atomic and committed explicitly.
# autoflush=False prevents premature writes before validation.
# -------------------------------------------------------------
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# -------------------------------------------------------------
# 4. Declarative Base Class
# All ORM models (e.g. User) will inherit from this Base.
# -------------------------------------------------------------
Base = declarative_base()

# -------------------------------------------------------------
# 5. FastAPI Database Session Dependency
# Guarantees each HTTP request receives an isolated database session
# and ensures the session is strictly closed after the response is sent,
# preventing database connection pool exhaustion.
# -------------------------------------------------------------
def get_db():
    """
    Generator dependency for FastAPI routes.
    Yields a database session, then closes it reliably in the finally block.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
