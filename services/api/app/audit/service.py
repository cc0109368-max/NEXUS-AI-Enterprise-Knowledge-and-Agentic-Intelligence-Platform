import json
from typing import Any, Dict, Optional
from app.core.database import DatabaseManager, db as default_db, new_id, utc_now_iso
from app.core.security import SensitiveDataRedactor

class AuditService:
    def __init__(self, database: Optional[DatabaseManager] = None):
        self.db = database or default_db

    def log_event(
        self,
        organization_id: str,
        event_type: str,
        resource_type: str,
        action: str,
        status: str = "SUCCESS",
        actor_user_id: Optional[str] = None,
        resource_id: Optional[str] = None,
        ip_address: str = "127.0.0.1",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        audit_id = new_id("aud")
        safe_meta = SensitiveDataRedactor.redact(json.dumps(metadata or {}))
        self.db.execute(
            '''
            INSERT INTO audit_logs (
                id, organization_id, actor_user_id, event_type, resource_type,
                resource_id, action, status, ip_address, metadata_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''',
            (
                audit_id,
                organization_id,
                actor_user_id,
                event_type,
                resource_type,
                resource_id,
                action,
                status,
                ip_address,
                safe_meta,
                utc_now_iso(),
            ),
        )
        return audit_id

    def list_logs(self, organization_id: str, limit: int = 100) -> list:
        rows = self.db.fetch_all(
            "SELECT * FROM audit_logs WHERE organization_id = ? ORDER BY created_at DESC LIMIT ?",
            (organization_id, limit),
        )
        for r in rows:
            try:
                r["metadata"] = json.loads(r.get("metadata_json") or "{}")
            except Exception:
                r["metadata"] = {}
        return rows
