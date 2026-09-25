import os
from pathlib import Path
from dotenv import load_dotenv

# Reliably find the backend directory and load .env regardless of working directory
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

class Settings:
    """
    Centralized configuration management.
    Reads environment variables from .env and system environment.
    """
    # Database connection URL
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./app.db")
    
    # Cloud providers (e.g. Neon, Render) frequently return 'postgres://' URLs,
    # but modern SQLAlchemy requires 'postgresql://' dialect prefix.
    if DATABASE_URL.startswith("postgres://"):
        DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)
        
    # JWT security configuration
    JWT_SECRET: str = os.getenv("JWT_SECRET", "default-fallback-insecure-secret-2026")
    JWT_ALGORITHM: str = os.getenv("JWT_ALGORITHM", "HS256")
    JWT_EXPIRE_MINUTES: int = int(os.getenv("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "120"))
    
    # Server network bindings
    PORT: int = int(os.getenv("PORT", "8000"))
    HOST: str = os.getenv("HOST", "0.0.0.0")

# Global singleton settings instance
settings = Settings()
