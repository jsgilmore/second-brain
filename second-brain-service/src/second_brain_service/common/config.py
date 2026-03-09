import os

from dotenv import load_dotenv


load_dotenv()


DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://brain:change-me@localhost:5432/brain")
API_PORT = int(os.environ.get("API_PORT", "8080"))
MCP_REMOTE_PORT = int(os.environ.get("MCP_REMOTE_PORT", "8000"))
EMBEDDING_DIMENSION = int(os.environ.get("EMBEDDING_DIMENSION", "3072"))
EMBEDDING_PROVIDER = os.environ.get("EMBEDDING_PROVIDER", "openai").strip().lower()
OPENAI_API_KEY = (os.environ.get("OPENAI_API_KEY") or "").strip() or None
OPENAI_BASE_URL = (os.environ.get("OPENAI_BASE_URL") or "").strip() or "https://api.openai.com/v1"
OPENAI_EMBEDDING_MODEL = os.environ.get("OPENAI_EMBEDDING_MODEL", "text-embedding-3-large")
OLLAMA_BASE_URL = (os.environ.get("OLLAMA_BASE_URL") or "http://localhost:11434").rstrip("/")
OLLAMA_EMBEDDING_MODEL = os.environ.get("OLLAMA_EMBEDDING_MODEL", "mxbai-embed-large")
ACTIVE_EMBEDDING_MODEL = OLLAMA_EMBEDDING_MODEL if EMBEDDING_PROVIDER == "ollama" else OPENAI_EMBEDDING_MODEL
EMBED_QUERY_PREFIX = os.environ.get(
    "EMBED_QUERY_PREFIX",
    "Represent this sentence for searching relevant passages: ",
)
CHUNK_SIZE = int(os.environ.get("CHUNK_SIZE", "6000"))
CHUNK_OVERLAP = int(os.environ.get("CHUNK_OVERLAP", "400"))
CHUNK_TARGET_TOKENS = int(os.environ.get("CHUNK_TARGET_TOKENS", "256"))
CHUNK_MAX_TOKENS = int(os.environ.get("CHUNK_MAX_TOKENS", "512"))
CHUNK_OVERLAP_TOKENS = int(os.environ.get("CHUNK_OVERLAP_TOKENS", "32"))
PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/")
DEFAULT_MAIL_SOURCE = os.environ.get("DEFAULT_MAIL_SOURCE", "gmail")
REMOTE_MCP_AUTH_REQUIRED = os.environ.get("REMOTE_MCP_AUTH_REQUIRED", "true").lower() in {"1", "true", "yes", "on"}
REMOTE_MCP_GOOGLE_CLIENT_ID = os.environ.get("REMOTE_MCP_GOOGLE_CLIENT_ID", "").strip()
REMOTE_MCP_GOOGLE_CLIENT_SECRET = os.environ.get("REMOTE_MCP_GOOGLE_CLIENT_SECRET", "").strip()
REMOTE_ALLOWED_EMAILS = [item.strip().lower() for item in os.environ.get("REMOTE_ALLOWED_EMAILS", "").split(",") if item.strip()]
REMOTE_ALLOWED_DOMAINS = [item.strip().lower() for item in os.environ.get("REMOTE_ALLOWED_DOMAINS", "").split(",") if item.strip()]
