import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path):
    """Tiny .env loader so connecting an API key is just editing one file.
    Existing environment variables win."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip("'\"")
        if key and value and key not in os.environ:
            os.environ[key] = value


_load_dotenv(BASE_DIR / ".env")
DATA_DIR = BASE_DIR / "data"
DB_PATH = Path(os.environ.get("MIKVAOS_DB", DATA_DIR / "mikvaos.db"))

# Models: Sonnet for everyday use, Opus for difficult sugyos (UI "strong" toggle),
# Haiku for the lightweight auto-tagging call.
ANSWER_MODEL = os.environ.get("ANSWER_MODEL", "claude-sonnet-4-6")
STRONG_MODEL = os.environ.get("STRONG_MODEL", "claude-opus-4-8")
TAGGING_MODEL = os.environ.get("TAGGING_MODEL", "claude-haiku-4-5")

# Embeddings (optional — semantic search is skipped when no key is set)
VOYAGE_API_KEY = os.environ.get("VOYAGE_API_KEY", "")
VOYAGE_MODEL = os.environ.get("VOYAGE_MODEL", "voyage-3.5")
VOYAGE_URL = "https://api.voyageai.com/v1/embeddings"

# Retrieval tuning
FTS_LIMIT = 30
EMBED_LIMIT = 15
REF_LIMIT = 25       # max rows pulled by direct reference detection
TOP_K = 20           # chunks sent to Claude
