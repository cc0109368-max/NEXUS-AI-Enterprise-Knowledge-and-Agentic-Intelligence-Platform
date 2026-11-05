import json
import time
from typing import Any, Dict, List, Optional
from app.core.database import DatabaseManager, db as default_db, new_id, utc_now_iso
from app.core.security import SensitiveDataRedactor

class ObservabilityService:
    '''
    Module J: OpenTelemetry-compatible tracing, structured JSON logging, and model usage accounting.
    '''
    def __init__(self, database: Optional[DatabaseManager] = None):
        self.db = database or default_db
        self._spans: List[Dict[str, Any]] = []

    def record_span(
        self,
        trace_id: str,
        organization_id: str,
        span_name: str,
        component: str,
        duration_ms: float,
        attributes: Optional[Dict[str, Any]] = None,
        status: str = "OK",
    ) -> Dict[str, Any]:
        safe_attrs = json.loads(SensitiveDataRedactor.redact(json.dumps(attributes or {})))
        span = {
            "span_id": new_id("spn"),
            "trace_id": trace_id,
            "organization_id": organization_id,
            "span_name": span_name,
            "component": component,
            "duration_ms": round(duration_ms, 2),
            "status": status,
            "attributes": safe_attrs,
            "timestamp": utc_now_iso(),
        }
        self._spans.append(span)
        return span

    def record_model_usage(
        self,
        organization_id: str,
        user_id: str,
        trace_id: str,
        provider: str,
        model_name: str,
        operation_type: str,
        prompt_tokens: int,
        completion_tokens: int,
        estimated_cost_usd: float,
        latency_ms: float,
    ) -> str:
        usage_id = new_id("usg")
        total_tokens = prompt_tokens + completion_tokens
        self.db.execute(
            '''
            INSERT INTO model_usage (
                id, organization_id, user_id, trace_id, provider, model_name,
                operation_type, prompt_tokens, completion_tokens, total_tokens,
                estimated_cost_usd, latency_ms, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''',
            (
                usage_id,
                organization_id,
                user_id,
                trace_id,
                provider,
                model_name,
                operation_type,
                prompt_tokens,
                completion_tokens,
                total_tokens,
                round(estimated_cost_usd, 6),
                round(latency_ms, 2),
                utc_now_iso(),
            ),
        )
        return usage_id

    def get_dashboard_metrics(self, organization_id: str) -> Dict[str, Any]:
        usage_rows = self.db.fetch_all(
            "SELECT * FROM model_usage WHERE organization_id = ? ORDER BY created_at DESC",
            (organization_id,),
        )
        doc_count = self.db.fetch_one(
            "SELECT COUNT(*) AS cnt FROM documents WHERE organization_id = ?",
            (organization_id,),
        )["cnt"]
        chunk_count = self.db.fetch_one(
            "SELECT COUNT(*) AS cnt FROM document_chunks WHERE organization_id = ?",
            (organization_id,),
        )["cnt"]
        agent_runs = self.db.fetch_all(
            "SELECT status, COUNT(*) AS cnt FROM agent_runs WHERE organization_id = ? GROUP BY status",
            (organization_id,),
        )
        eval_runs = self.db.fetch_all(
            "SELECT * FROM evaluation_runs WHERE organization_id = ? ORDER BY created_at DESC LIMIT 5",
            (organization_id,),
        )

        total_tokens = sum(r["total_tokens"] for r in usage_rows)
        total_cost = sum(r["estimated_cost_usd"] for r in usage_rows)
        avg_latency = (
            sum(r["latency_ms"] for r in usage_rows) / len(usage_rows) if usage_rows else 0.0
        )

        org_spans = [s for s in self._spans if s["organization_id"] == organization_id]
        return {
            "organization_id": organization_id,
            "request_volume": len(usage_rows),
            "avg_model_latency_ms": round(avg_latency, 2),
            "total_tokens_consumed": total_tokens,
            "estimated_total_cost_usd": round(total_cost, 6),
            "indexed_documents": doc_count,
            "indexed_chunks": chunk_count,
            "agent_runs_by_status": {r["status"]: r["cnt"] for r in agent_runs},
            "recent_evaluation_runs": len(eval_runs),
            "recent_traces": org_spans[-25:],
            "model_usage_breakdown": usage_rows[:20],
        }
