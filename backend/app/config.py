"""Central configuration. Every setting comes from environment variables / the .env file."""
import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


class Settings:
    MONGODB_URI = os.getenv("MONGODB_URI", "").strip()
    MONGODB_DB = os.getenv("MONGODB_DB", "itsm_helpdesk")

    EMBEDDING_BACKEND = os.getenv("EMBEDDING_BACKEND", "auto")
    EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
    LLM_BACKEND = os.getenv("LLM_BACKEND", "auto")
    LLM_MODEL = os.getenv("LLM_MODEL", "Qwen/Qwen2.5-0.5B-Instruct")

    CONFIDENCE_THRESHOLD = float(os.getenv("CONFIDENCE_THRESHOLD", "0.45"))
    TOP_K = int(os.getenv("TOP_K", "3"))

    SERVICENOW_INSTANCE = os.getenv("SERVICENOW_INSTANCE", "").strip()
    SERVICENOW_USER = os.getenv("SERVICENOW_USER", "").strip()
    SERVICENOW_PASSWORD = os.getenv("SERVICENOW_PASSWORD", "").strip()

    # Vector DB (Qdrant). Default = local mode stored in backend/vector_store/qdrant (free, no account needed).
    QDRANT_PATH = os.getenv("QDRANT_PATH", "qdrant")        # folder name, or ":memory:"
    QDRANT_URL = os.getenv("QDRANT_URL", "").strip()        # optional: http://localhost:6333 or a Qdrant Cloud free cluster URL
    QDRANT_API_KEY = os.getenv("QDRANT_API_KEY", "").strip()

    CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",")]
    PROVISIONING_SECONDS = int(os.getenv("PROVISIONING_SECONDS", "20"))

    KB_DIR = BASE_DIR / "knowledge_base"
    VECTOR_DIR = BASE_DIR / "vector_store"

    @property
    def servicenow_real(self) -> bool:
        return bool(self.SERVICENOW_INSTANCE and self.SERVICENOW_USER and self.SERVICENOW_PASSWORD)

    @property
    def servicenow_base(self) -> str:
        inst = self.SERVICENOW_INSTANCE
        if inst.startswith("http"):
            return inst.rstrip("/")
        return f"https://{inst}.service-now.com"


settings = Settings()
