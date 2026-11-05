import base64
import hashlib
import hmac
import json
import re
import secrets
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple
from packages.shared_contracts.schemas import ROLE_HIERARCHY, CLASSIFICATION_TO_MIN_ROLE
from .config import settings

class SecurityViolationError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 403):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code

@dataclass(frozen=True)
class TenantRequestContext:
    user_id: str
    email: str
    organization_id: str
    role: str
    trace_id: str

    def has_min_role(self, min_role: str) -> bool:
        user_rank = ROLE_HIERARCHY.get(self.role, 0)
        req_rank = ROLE_HIERARCHY.get(min_role, 99)
        return user_rank >= req_rank

    def can_access_classification(self, classification: str) -> bool:
        min_role = CLASSIFICATION_TO_MIN_ROLE.get(classification, "ADMIN")
        return self.has_min_role(min_role)

def hash_password(password: str, salt: Optional[str] = None) -> str:
    if len(password) < 8:
        raise ValueError("Password must be at least 8 characters long.")
    salt_hex = salt or secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), 260000)
    return f"pbkdf2_sha256$260000${salt_hex}${dk.hex()}"

def verify_password(password: str, stored_hash: str) -> bool:
    try:
        algo, iterations_str, salt_hex, hash_hex = stored_hash.split("$")
        dk = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(iterations_str)
        )
        return hmac.compare_digest(dk.hex(), hash_hex)
    except Exception:
        return False

def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")

def _b64url_decode(s: str) -> bytes:
    pad = "=" * ((4 - len(s) % 4) % 4)
    return base64.urlsafe_b64decode((s + pad).encode("ascii"))

def create_jwt_token(payload: Dict[str, Any], expires_in_seconds: int = 3600) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    now = int(time.time())
    body = {**payload, "iat": now, "exp": now + expires_in_seconds, "jti": secrets.token_hex(8)}
    signing_input = f"{_b64url_encode(json.dumps(header).encode())}.{_b64url_encode(json.dumps(body).encode())}"
    sig = hmac.new(settings.jwt_secret.encode("utf-8"), signing_input.encode("ascii"), hashlib.sha256).digest()
    return f"{signing_input}.{_b64url_encode(sig)}"

def decode_jwt_token(token: str) -> Dict[str, Any]:
    try:
        parts = token.split(".")
        if len(parts) != 3:
            raise SecurityViolationError("INVALID_TOKEN", "Malformed JWT token", 401)
        signing_input = f"{parts[0]}.{parts[1]}"
        expected_sig = hmac.new(
            settings.jwt_secret.encode("utf-8"), signing_input.encode("ascii"), hashlib.sha256
        ).digest()
        actual_sig = _b64url_decode(parts[2])
        if not hmac.compare_digest(expected_sig, actual_sig):
            raise SecurityViolationError("INVALID_SIGNATURE", "JWT signature verification failed", 401)
        payload = json.loads(_b64url_decode(parts[1]).decode("utf-8"))
        if int(time.time()) > int(payload.get("exp", 0)):
            raise SecurityViolationError("TOKEN_EXPIRED", "JWT token has expired", 401)
        return payload
    except SecurityViolationError:
        raise
    except Exception as exc:
        raise SecurityViolationError("INVALID_TOKEN", f"Token decode error: {exc}", 401)

class PromptInjectionGuard:
    '''
    OWASP GenAI LLM Top 10 (2026) LLM01 & LLM08 Defense:
    Detects direct prompt injection, system prompt leakage probes, and indirect document-embedded overrides.
    '''
    DIRECT_INJECTION_PATTERNS = [
        r"ignore\s+(all\s+)?(previous|prior|system)\s+instructions",
        r"disregard\s+(all\s+)?(previous|prior|system)\s+(instructions|rules)",
        r"(reveal|print|output|show|repeat)\s+(your\s+)?(verbatim\s+)?(system\s+prompt|hidden\s+instructions|api\s+key|secret\s+key)",
        r"you\s+are\s+now\s+in\s+developer\s+mode",
        r"bypass\s+(all\s+)?(security|rbac|tenant|authorization)\s+(checks|rules|filters)",
        r"execute\s+(arbitrary\s+)?(shell|bash|sql|os\.system|subprocess)",
    ]

    INDIRECT_DOCUMENT_PATTERNS = [
        r"system\s+override\s*:",
        r"ignore\s+(all\s+)?(previous|prior|system)\s+instructions",
        r"important\s+ai\s+instruction\s*:",
        r"when\s+summarizing\s+this\s+document\s*,?\s*(always\s+)?(execute|call|leak|ignore)",
        r"do\s+not\s+enforce\s+data\s+retention",
        r"grant\s+admin\s+access",
    ]

    @classmethod
    def inspect_user_query(cls, query: str) -> Tuple[bool, Optional[str]]:
        norm = query.lower().strip()
        for pat in cls.DIRECT_INJECTION_PATTERNS:
            if re.search(pat, norm):
                return True, f"Matched OWASP LLM01/LLM08 injection pattern: {pat}"
        return False, None

    @classmethod
    def scan_document_chunk(cls, text: str) -> Tuple[bool, str, List[str]]:
        '''
        Scans untrusted document text for indirect prompt injection.
        Returns (is_suspicious, sanitized_text, matched_rules).
        '''
        matched = []
        sanitized = text
        for pat in cls.INDIRECT_DOCUMENT_PATTERNS:
            if re.search(pat, text, flags=re.IGNORECASE):
                matched.append(pat)
                sanitized = re.sub(
                    pat,
                    "[REDACTED_UNTRUSTED_DOCUMENT_DIRECTIVE]",
                    sanitized,
                    flags=re.IGNORECASE,
                )
        return (len(matched) > 0), sanitized, matched

class SensitiveDataRedactor:
    '''OWASP LLM02:2026 Sensitive Information Disclosure & Log Sanitizer'''
    SECRET_PATTERNS = [
        (r"AIza[0-9A-Za-z\-_]{20,}", "[REDACTED_GEMINI_KEY]"),
        (r"sk-[0-9A-Za-z]{16,}", "[REDACTED_API_KEY]"),
        (r"Bearer\s+[A-Za-z0-9\-_]+\.[A-Za-z0-9\-_]+\.[A-Za-z0-9\-_]+", "Bearer [REDACTED_JWT]"),
        (r"\b\d{3}-\d{2}-\d{4}\b", "[REDACTED_SSN]"),
    ]

    @classmethod
    def redact(cls, text: str) -> str:
        if not text:
            return text
        out = text
        for pattern, replacement in cls.SECRET_PATTERNS:
            out = re.sub(pattern, replacement, out)
        return out

class RateLimiter:
    '''OWASP LLM06:2026 Unbounded Consumption Protection'''
    def __init__(self):
        self._buckets: Dict[str, List[float]] = {}

    def check_limit(self, key: str, max_requests: int = 120, window_seconds: int = 60) -> bool:
        now = time.time()
        history = [t for t in self._buckets.get(key, []) if now - t < window_seconds]
        if len(history) >= max_requests:
            self._buckets[key] = history
            return False
        history.append(now)
        self._buckets[key] = history
        return True

rate_limiter = RateLimiter()
