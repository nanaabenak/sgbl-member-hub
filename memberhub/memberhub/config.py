"""Environment-driven configuration.

PostgreSQL is addressed through DATABASE_URL, so moving from a local EC2
installation to Amazon RDS only requires changing one environment variable.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def _bool(name: str, default: bool = False) -> bool:
    return os.environ.get(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


class Config:
    # Required in production. A development default keeps local setup friendly;
    # deploy.sh always generates a strong random value.
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-only-change-this-secret-key")

    # postgresql://user:password@host:port/database
    DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql:///sgbl_member_hub")

    SESSION_COOKIE_NAME = "sgbl_session"
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = _bool("SESSION_COOKIE_SECURE", False)
    PERMANENT_SESSION_LIFETIME_SECONDS = int(os.environ.get("SESSION_LIFETIME_SECONDS", "43200"))
    SESSION_IDLE_TIMEOUT_SECONDS = int(os.environ.get("SESSION_IDLE_TIMEOUT_SECONDS", "7200"))

    # The existing Builder Card site is served alongside the hub by Nginx at /card/.
    BUILDER_CARD_URL = os.environ.get("BUILDER_CARD_URL", "/card/")

    CLUB_NAME = os.environ.get("CLUB_NAME", "AWS Student Builder Group")
    MAX_CONTENT_LENGTH = 2 * 1024 * 1024  # 2 MB: this app stores links and notes only

    PREFERRED_URL_SCHEME = "https" if _bool("BEHIND_HTTPS_PROXY", False) else "http"


class DevelopmentConfig(Config):
    DEBUG = True
    SESSION_COOKIE_SECURE = False


class TestingConfig(Config):
    TESTING = True
    DEBUG = False
    SESSION_COOKIE_SECURE = False
    WTF_CSRF_ENABLED = True


class ProductionConfig(Config):
    DEBUG = False
    # Secure by default. A restricted lab with HTTP-only access can set
    # SESSION_COOKIE_SECURE=false explicitly; real deployments should keep true.
    SESSION_COOKIE_SECURE = _bool("SESSION_COOKIE_SECURE", True)


def config_from_env() -> type[Config]:
    name = os.environ.get("FLASK_CONFIG", "production").strip().lower()
    return {
        "development": DevelopmentConfig,
        "testing": TestingConfig,
        "production": ProductionConfig,
    }.get(name, ProductionConfig)
