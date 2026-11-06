import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

class Config:
    """Production configuration for DocSphere AI platform."""
    
    # Base paths
    BASE_DIR = Path(__file__).resolve().parent
    
    # Flask settings
    SECRET_KEY = os.getenv("SECRET_KEY", "docusphere_super_secret_jwt_and_session_key_2026")
    ADMIN_INVITE_CODE = os.getenv("ADMIN_INVITE_CODE", "DOCSPHERE_ADMIN_2026")
    FLASK_ENV = os.getenv("FLASK_ENV", "development")
    PORT = int(os.getenv("PORT", 5000))
    DEBUG = FLASK_ENV == "development"
    
    # Database and Local File Storage
    DB_PATH = os.path.join(BASE_DIR, os.getenv("DB_PATH", "db/docusphere.db"))
    UPLOAD_FOLDER = os.path.join(BASE_DIR, os.getenv("UPLOAD_FOLDER", "uploads"))
    INDEX_FOLDER = os.path.join(BASE_DIR, os.getenv("INDEX_FOLDER", "indices"))
    
    # Max file upload size (50MB)
    MAX_CONTENT_LENGTH = 50 * 1024 * 1024
    
    # Allowed Document Extensions for Multi-Format Ingestion
    ALLOWED_EXTENSIONS = {
        'pdf',
        'docx',
        'doc',
        'txt',
        'html',
        'htm',
        'xml',
        'xbrl'
    }
    
    # LLM Settings (Groq / OpenAI compatible)
    GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
    GROQ_API_BASE = os.getenv("GROQ_API_BASE", "https://api.groq.com/openai/v1")
    _configured_model = os.getenv("GROQ_CHAT_MODEL", "qwen/qwen3.8-27b")
    # Guard against non-existent or deprecated models (e.g. llama-3.1-8b-instant or 3.3-70b)
    if not _configured_model or "llama" in _configured_model.lower() or "3.3-70b" in _configured_model.lower():
        GROQ_CHAT_MODEL = "qwen/qwen3.8-27b"
    else:
        GROQ_CHAT_MODEL = _configured_model
    FALLBACK_CHAT_MODEL = "openai/gpt-oss-20b"
    
    # Local Dense Embeddings (SentenceTransformers)
    EMBEDDING_MODEL_NAME = os.getenv("EMBEDDING_MODEL_NAME", "all-MiniLM-L6-v2")
    
    # Chunker Hyperparameters
    CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", 800))
    CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", 150))
    
    # Hybrid Retrieval (Dense Vector + Sparse BM25)
    TOP_K_RETRIEVAL = int(os.getenv("TOP_K_RETRIEVAL", 5))
    HYBRID_ALPHA = float(os.getenv("HYBRID_ALPHA", 0.6))  # 0.6 Dense, 0.4 Sparse
    
    # 4-Agent Self-Correction Loop
    MAX_VERIFICATION_ATTEMPTS = int(os.getenv("MAX_VERIFICATION_ATTEMPTS", 3))
    MAX_GENERATION_TOKENS = int(os.getenv("MAX_GENERATION_TOKENS", 2048))

    @classmethod
    def ensure_directories(cls):
        """Ensures that all storage directories exist."""
        os.makedirs(os.path.dirname(cls.DB_PATH), exist_ok=True)
        os.makedirs(cls.UPLOAD_FOLDER, exist_ok=True)
        os.makedirs(cls.INDEX_FOLDER, exist_ok=True)

# Auto-ensure required directories on module load
Config.ensure_directories()
