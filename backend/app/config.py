"""Application settings, loaded from environment variables / the repo-root .env file."""
import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND_DIR.parent

load_dotenv(REPO_ROOT / ".env")


def _env(name: str, default: str | None = None) -> str | None:
    value = (os.getenv(name) or "").strip()
    return value if value else default


def _is_placeholder(value: str) -> bool:
    # Values copied unchanged from .env.example, e.g. "your-gemini-key-here".
    return value.lower().startswith("your-") and value.lower().endswith("-here")


def _secret(name: str) -> str | None:
    """An API key from the environment; empty or placeholder values count as not set."""
    value = _env(name)
    return None if value is None or _is_placeholder(value) else value


@dataclass(frozen=True)
class Settings:
    gemini_api_key: str | None = field(default_factory=lambda: _secret("GEMINI_API_KEY"))
    gemini_model: str = field(default_factory=lambda: _env("GEMINI_MODEL", "gemini-2.5-flash"))
    # Optional: without it S2 is called unauthenticated (shared, heavily rate-limited pool).
    s2_api_key: str | None = field(default_factory=lambda: _secret("SEMANTIC_SCHOLAR_API_KEY"))
    s2_base_url: str = field(
        default_factory=lambda: _env("S2_BASE_URL", "https://api.semanticscholar.org/graph/v1")
    )
    arxiv_base_url: str = field(
        default_factory=lambda: _env("ARXIV_BASE_URL", "https://export.arxiv.org/api/query")
    )
    data_dir: Path = field(default_factory=lambda: Path(_env("DATA_DIR", str(BACKEND_DIR / "data"))))
    database_url: str | None = field(default_factory=lambda: _env("DATABASE_URL"))
    user_agent: str = field(
        default_factory=lambda: _env(
            "HTTP_USER_AGENT", "ResearchAssistant/0.1 (course project; python-httpx)"
        )
    )

    @property
    def upload_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def db_url(self) -> str:
        return self.database_url or f"sqlite:///{self.data_dir / 'app.db'}"


settings = Settings()
