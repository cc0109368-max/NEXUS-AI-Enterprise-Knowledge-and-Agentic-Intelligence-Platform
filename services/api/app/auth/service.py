import hashlib
import secrets
from typing import Any, Dict, Optional
from app.core.database import DatabaseManager, db as default_db, new_id, utc_now_iso
from app.core.config import settings
from app.core.security import (
    SecurityViolationError,
    TenantRequestContext,
    create_jwt_token,
    decode_jwt_token,
    hash_password,
    verify_password,
)
from app.audit.service import AuditService

class AuthService:
    def __init__(self, database: Optional[DatabaseManager] = None):
        self.db = database or default_db
        self.audit = AuditService(self.db)

    def register_user(self, email: str, password: str, full_name: str) -> Dict[str, Any]:
        norm_email = email.strip().lower()
        existing = self.db.fetch_one("SELECT id FROM users WHERE email = ?", (norm_email,))
        if existing:
            raise ValueError(f"User with email {norm_email} already exists.")
        user_id = new_id("usr")
        pw_hash = hash_password(password)
        now = utc_now_iso()
        self.db.execute(
            '''
            INSERT INTO users (id, email, password_hash, full_name, is_active, created_at, updated_at)
            VALUES (?, ?, ?, ?, 1, ?, ?)
            ''',
            (user_id, norm_email, pw_hash, full_name.strip(), now, now),
        )
        return {"id": user_id, "email": norm_email, "full_name": full_name.strip(), "created_at": now}

    def login(self, email: str, password: str) -> Dict[str, Any]:
        norm_email = email.strip().lower()
        user = self.db.fetch_one("SELECT * FROM users WHERE email = ?", (norm_email,))
        if not user or not verify_password(password, user["password_hash"]):
            self.audit.log_event(
                organization_id="system",
                event_type="AUTH_LOGIN_FAILED",
                resource_type="user",
                action="login",
                status="DENIED",
                metadata={"email": norm_email},
            )
            raise SecurityViolationError("INVALID_CREDENTIALS", "Invalid email or password", 401)
        if not user["is_active"]:
            raise SecurityViolationError("ACCOUNT_DISABLED", "User account is disabled", 403)

        memberships = self.db.fetch_all(
            '''
            SELECT om.organization_id, om.role, o.name AS org_name, o.slug AS org_slug
            FROM organization_members om
            JOIN organizations o ON o.id = om.organization_id
            WHERE om.user_id = ?
            ''',
            (user["id"],),
        )
        raw_refresh = secrets.token_urlsafe(32)
        refresh_hash = hashlib.sha256(raw_refresh.encode("utf-8")).hexdigest()
        self.db.execute(
            "UPDATE users SET refresh_token_hash = ?, updated_at = ? WHERE id = ?",
            (refresh_hash, utc_now_iso(), user["id"]),
        )
        access_token = create_jwt_token(
            {"sub": user["id"], "email": user["email"], "name": user["full_name"]},
            expires_in_seconds=settings.access_token_expire_minutes * 60,
        )
        return {
            "access_token": access_token,
            "refresh_token": raw_refresh,
            "token_type": "bearer",
            "user": {
                "id": user["id"],
                "email": user["email"],
                "full_name": user["full_name"],
                "organizations": memberships,
            },
        }

    def rotate_refresh_token(self, user_id: str, refresh_token: str) -> Dict[str, str]:
        user = self.db.fetch_one("SELECT * FROM users WHERE id = ?", (user_id,))
        if not user or not user.get("refresh_token_hash"):
            raise SecurityViolationError("INVALID_REFRESH", "Refresh session not found", 401)
        candidate_hash = hashlib.sha256(refresh_token.encode("utf-8")).hexdigest()
        if candidate_hash != user["refresh_token_hash"]:
            self.db.execute("UPDATE users SET refresh_token_hash = NULL WHERE id = ?", (user_id,))
            raise SecurityViolationError("REFRESH_REUSE_DETECTED", "Invalid refresh token", 401)
        new_raw = secrets.token_urlsafe(32)
        new_hash = hashlib.sha256(new_raw.encode("utf-8")).hexdigest()
        self.db.execute(
            "UPDATE users SET refresh_token_hash = ?, updated_at = ? WHERE id = ?",
            (new_hash, utc_now_iso(), user_id),
        )
        access_token = create_jwt_token(
            {"sub": user["id"], "email": user["email"], "name": user["full_name"]},
            expires_in_seconds=settings.access_token_expire_minutes * 60,
        )
        return {"access_token": access_token, "refresh_token": new_raw, "token_type": "bearer"}

    def authorize_request(
        self,
        access_token: str,
        organization_id: str,
        min_role: str = "MEMBER",
        trace_id: Optional[str] = None,
    ) -> TenantRequestContext:
        payload = decode_jwt_token(access_token)
        user_id = payload["sub"]
        membership = self.db.fetch_one(
            "SELECT role FROM organization_members WHERE organization_id = ? AND user_id = ?",
            (organization_id, user_id),
        )
        if not membership:
            self.audit.log_event(
                organization_id=organization_id,
                actor_user_id=user_id,
                event_type="CROSS_TENANT_ACCESS_BLOCKED",
                resource_type="organization",
                resource_id=organization_id,
                action="authorize_request",
                status="BLOCKED",
            )
            raise SecurityViolationError(
                "TENANT_ACCESS_DENIED",
                f"User {user_id} is not an authorized member of organization {organization_id}",
                403,
            )
        ctx = TenantRequestContext(
            user_id=user_id,
            email=payload["email"],
            organization_id=organization_id,
            role=membership["role"],
            trace_id=trace_id or new_id("trc"),
        )
        if not ctx.has_min_role(min_role):
            self.audit.log_event(
                organization_id=organization_id,
                actor_user_id=user_id,
                event_type="INSUFFICIENT_ROLE_BLOCKED",
                resource_type="organization",
                resource_id=organization_id,
                action=f"require_{min_role}",
                status="BLOCKED",
                metadata={"user_role": ctx.role, "required_role": min_role},
            )
            raise SecurityViolationError(
                "INSUFFICIENT_ROLE",
                f"Operation requires minimum role {min_role}, current role is {ctx.role}",
                403,
            )
        return ctx
