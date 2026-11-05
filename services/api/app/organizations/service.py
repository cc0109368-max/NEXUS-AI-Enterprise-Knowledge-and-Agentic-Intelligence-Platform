import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from app.core.database import DatabaseManager, db as default_db, new_id, utc_now_iso
from app.core.security import SecurityViolationError, TenantRequestContext
from app.audit.service import AuditService

class OrganizationService:
    def __init__(self, database: Optional[DatabaseManager] = None):
        self.db = database or default_db
        self.audit = AuditService(self.db)

    def create_organization(
        self, user_id: str, name: str, slug: str, plan_tier: str = "ENTERPRISE"
    ) -> Dict[str, Any]:
        org_id = new_id("org")
        ws_id = new_id("ws")
        mem_id = new_id("mem")
        now = utc_now_iso()
        clean_slug = slug.strip().lower()

        with self.db.connection() as conn:
            conn.execute(
                '''
                INSERT INTO organizations (id, name, slug, plan_tier, max_monthly_tokens, created_at)
                VALUES (?, ?, ?, ?, 10000000, ?)
                ''',
                (org_id, name.strip(), clean_slug, plan_tier, now),
            )
            conn.execute(
                '''
                INSERT INTO organization_members (id, organization_id, user_id, role, joined_at)
                VALUES (?, ?, ?, 'OWNER', ?)
                ''',
                (mem_id, org_id, user_id, now),
            )
            conn.execute(
                '''
                INSERT INTO workspaces (id, organization_id, name, description, access_level, created_by, created_at)
                VALUES (?, ?, 'General Enterprise Workspace', 'Default knowledge and agent workspace', 'ORG_WIDE', ?, ?)
                ''',
                (ws_id, org_id, user_id, now),
            )

        self.audit.log_event(
            organization_id=org_id,
            actor_user_id=user_id,
            event_type="ORGANIZATION_CREATED",
            resource_type="organization",
            resource_id=org_id,
            action="create",
            metadata={"slug": clean_slug, "default_workspace_id": ws_id},
        )
        return {
            "id": org_id,
            "name": name.strip(),
            "slug": clean_slug,
            "plan_tier": plan_tier,
            "role": "OWNER",
            "default_workspace_id": ws_id,
            "created_at": now,
        }

    def create_workspace(
        self, ctx: TenantRequestContext, name: str, description: str = "", access_level: str = "ORG_WIDE"
    ) -> Dict[str, Any]:
        if not ctx.has_min_role("MANAGER"):
            raise SecurityViolationError("INSUFFICIENT_ROLE", "Requires MANAGER or higher to create workspaces", 403)
        ws_id = new_id("ws")
        now = utc_now_iso()
        self.db.execute(
            '''
            INSERT INTO workspaces (id, organization_id, name, description, access_level, created_by, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ''',
            (ws_id, ctx.organization_id, name.strip(), description, access_level, ctx.user_id, now),
        )
        self.audit.log_event(
            organization_id=ctx.organization_id,
            actor_user_id=ctx.user_id,
            event_type="WORKSPACE_CREATED",
            resource_type="workspace",
            resource_id=ws_id,
            action="create",
            metadata={"name": name.strip()},
        )
        return {
            "id": ws_id,
            "organization_id": ctx.organization_id,
            "name": name.strip(),
            "description": description,
            "access_level": access_level,
            "created_at": now,
        }

    def list_workspaces(self, ctx: TenantRequestContext) -> List[Dict[str, Any]]:
        return self.db.fetch_all(
            "SELECT * FROM workspaces WHERE organization_id = ? ORDER BY created_at ASC",
            (ctx.organization_id,),
        )

    def add_or_invite_member(
        self, ctx: TenantRequestContext, email: str, role: str, user_id_if_exists: Optional[str] = None
    ) -> Dict[str, Any]:
        if not ctx.has_min_role("ADMIN"):
            raise SecurityViolationError("INSUFFICIENT_ROLE", "Requires ADMIN or OWNER to invite members", 403)
        norm_email = email.strip().lower()
        now = utc_now_iso()
        user = self.db.fetch_one("SELECT id FROM users WHERE email = ?", (norm_email,))
        target_uid = user_id_if_exists or (user["id"] if user else None)
        if target_uid:
            mem_id = new_id("mem")
            self.db.execute(
                '''
                INSERT OR REPLACE INTO organization_members (id, organization_id, user_id, role, joined_at)
                VALUES (?, ?, ?, ?, ?)
                ''',
                (mem_id, ctx.organization_id, target_uid, role, now),
            )
            self.audit.log_event(
                organization_id=ctx.organization_id,
                actor_user_id=ctx.user_id,
                event_type="MEMBER_ADDED",
                resource_type="organization_member",
                resource_id=target_uid,
                action="assign_role",
                metadata={"email": norm_email, "role": role},
            )
            return {"status": "ADDED", "user_id": target_uid, "email": norm_email, "role": role}

        inv_id = new_id("inv")
        raw_token = secrets.token_urlsafe(24)
        token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
        expires = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
        self.db.execute(
            '''
            INSERT INTO invitations (id, organization_id, email, role, token_hash, status, expires_at, created_by, created_at)
            VALUES (?, ?, ?, ?, ?, 'PENDING', ?, ?, ?)
            ''',
            (inv_id, ctx.organization_id, norm_email, role, token_hash, expires, ctx.user_id, now),
        )
        return {"status": "INVITED", "invitation_id": inv_id, "email": norm_email, "role": role}

    def list_members(self, ctx: TenantRequestContext) -> List[Dict[str, Any]]:
        return self.db.fetch_all(
            '''
            SELECT om.id, om.user_id, om.role, om.joined_at, u.email, u.full_name
            FROM organization_members om
            JOIN users u ON u.id = om.user_id
            WHERE om.organization_id = ?
            ORDER BY om.joined_at ASC
            ''',
            (ctx.organization_id,),
        )
