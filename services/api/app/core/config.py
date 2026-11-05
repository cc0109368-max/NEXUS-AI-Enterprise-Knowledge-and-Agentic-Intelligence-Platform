import os
from dataclasses import dataclass

@dataclass
class Settings:
    env: str = os.getenv("NEXUS_ENV", "development")
    db_path: str = os.getenv("NEXUS_DB_PATH", "/tmp/nexus-ai/nexus_ai.db")
    db_url: str = os.getenv("NEXUS_DB_URL", "postgresql://nexus:nexus_dev_password@localhost:5432/nexus_ai")
    jwt_secret: str = os.getenv("NEXUS_JWT_SECRET", "nexus-enterprise-hmac-sha256-secret-key-2026-v1")
    access_token_expire_minutes: int = int(os.getenv("NEXUS_ACCESS_TOKEN_EXPIRE_MINUTES", "60"))
    refresh_token_expire_days: int = int(os.getenv("NEXUS_REFRESH_TOKEN_EXPIRE_DAYS", "14"))
    primary_provider: str = os.getenv("NEXUS_PRIMARY_PROVIDER", "gemini")
    gemini_api_key: str = os.getenv("GEMINI_API_KEY", "")
    gemini_chat_model: str = os.getenv("GEMINI_CHAT_MODEL", "gemini-3.8-flash")
    gemini_fast_model: str = os.getenv("GEMINI_FAST_MODEL", "gemini-3.5-flash-lite")
    gemini_embedding_model: str = os.getenv("GEMINI_EMBEDDING_MODEL", "gemini-embedding-001")
    embedding_dimensions: int = int(os.getenv("GEMINI_EMBEDDING_DIMENSIONS", "128"))
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    openai_chat_model: str = os.getenv("OPENAI_CHAT_MODEL", "gpt-4o-mini")
    openai_embedding_model: str = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
    max_upload_bytes: int = int(os.getenv("NEXUS_MAX_UPLOAD_BYTES", str(25 * 1024 * 1024)))
    max_documents_per_org: int = int(os.getenv("NEXUS_MAX_DOCUMENTS_PER_ORG", "500"))
    max_context_tokens: int = int(os.getenv("NEXUS_MAX_CONTEXT_TOKENS", "6000"))
    max_response_tokens: int = int(os.getenv("NEXUS_MAX_RESPONSE_TOKENS", "2048"))
    agent_max_steps: int = int(os.getenv("NEXUS_AGENT_MAX_STEPS", "12"))
    agent_max_tool_calls: int = int(os.getenv("NEXUS_AGENT_MAX_TOOL_CALLS", "6"))
    rrf_k: int = int(os.getenv("NEXUS_RRF_K", "60"))
    rate_limit_requests_per_minute: int = int(os.getenv("NEXUS_RATE_LIMIT_RPM", "120"))

settings = Settings()
