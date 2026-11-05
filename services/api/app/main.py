import base64
from typing import Any, Dict, Optional
from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from packages.shared_contracts.schemas import (
    AgentRunRequest,
    AnalyticsQueryRequest,
    ApiError,
    ApiResponse,
    ApprovalDecisionRequest,
    ConversationCreateRequest,
    DocumentComparisonRequest,
    DocumentUploadRequest,
    FeedbackCreateRequest,
    InvitationCreateRequest,
    MessageCreateRequest,
    OrganizationCreateRequest,
    RetrievalQueryRequest,
    UserLoginRequest,
    UserRegisterRequest,
    WorkspaceCreateRequest,
)
from packages.llm_core.provider import get_llm_provider
from app.core.config import settings
from app.core.database import db, new_id, utc_now_iso
from app.core.security import SecurityViolationError, TenantRequestContext, decode_jwt_token, rate_limiter
from app.auth.service import AuthService
from app.organizations.service import OrganizationService
from app.documents.service import DocumentIntelligenceService
from app.retrieval.service import HybridRAGEngine
from app.conversations.service import ConversationService
from app.agents.service import SupervisorAgentOrchestrator
from app.tools.service import ControlledToolRegistry
from app.analytics.service import DataAnalyticsService
from app.reports.service import DocumentComparisonService
from app.evaluation.service import EvaluationBenchmarkEngine
from app.observability.tracer import ObservabilityService
from app.audit.service import AuditService

app = FastAPI(
    title="NEXUS AI — Enterprise Knowledge & Agentic Intelligence API",
    version="1.0.0",
    description="Versioned Enterprise API (/api/v1) for Hybrid RAG, LangGraph Multi-Agent Orchestration, Deterministic Analytics, Evaluation, and OWASP 2026 Security.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

obs_service = ObservabilityService(db)
auth_service = AuthService(db)
org_service = OrganizationService(db)
doc_service = DocumentIntelligenceService(db, obs_service)
rag_engine = HybridRAGEngine(db, obs_service)
conv_service = ConversationService(db, obs_service)
agent_orchestrator = SupervisorAgentOrchestrator(db, obs_service)
tool_registry = ControlledToolRegistry(db)
analytics_service = DataAnalyticsService(db)
report_service = DocumentComparisonService(db)
eval_engine = EvaluationBenchmarkEngine(db, obs_service)
audit_service = AuditService(db)

@app.exception_handler(SecurityViolationError)
async def security_exception_handler(request: Request, exc: SecurityViolationError):
    trace_id = request.headers.get("X-Trace-Id", new_id("trc"))
    return JSONResponse(
        status_code=exc.status_code,
        content=ApiError(error_code=exc.code, message=exc.message, trace_id=trace_id).dict(),
    )

@app.exception_handler(ValueError)
async def value_error_handler(request: Request, exc: ValueError):
    trace_id = request.headers.get("X-Trace-Id", new_id("trc"))
    return JSONResponse(
        status_code=400,
        content=ApiError(error_code="VALIDATION_ERROR", message=str(exc), trace_id=trace_id).dict(),
    )

def _extract_bearer(authorization: Optional[str]) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise SecurityViolationError("MISSING_BEARER_TOKEN", "Authorization: Bearer <token> header required", 401)
    return authorization.split(" ", 1)[1].strip()

def _require_context(
    authorization: Optional[str],
    x_organization_id: Optional[str],
    min_role: str = "MEMBER",
) -> TenantRequestContext:
    token = _extract_bearer(authorization)
    if not x_organization_id:
        raise SecurityViolationError("MISSING_ORG_HEADER", "X-Organization-Id header is required", 400)
    if not rate_limiter.check_limit(f"{x_organization_id}:{token[:16]}", settings.rate_limit_requests_per_minute):
        raise SecurityViolationError("RATE_LIMIT_EXCEEDED", "Per-minute API rate limit exceeded", 429)
    return auth_service.authorize_request(token, x_organization_id, min_role=min_role)

# 1. Health & Readiness
@app.get("/api/v1/health")
def health_check():
    return ApiResponse(
        data={
            "status": "healthy",
            "service": "nexus-ai-api",
            "version": "1.0.0",
            "timestamp": utc_now_iso(),
            "provider_status": get_llm_provider().get_status(),
        },
        trace_id=new_id("trc"),
    )

@app.get("/api/v1/ready")
def readiness_check():
    user_cnt = db.fetch_one("SELECT COUNT(*) AS cnt FROM users")["cnt"]
    return ApiResponse(
        data={"status": "ready", "database": "connected", "registered_users": user_cnt},
        trace_id=new_id("trc"),
    )

# 2. Authentication APIs
@app.post("/api/v1/auth/register")
def register(req: UserRegisterRequest):
    user = auth_service.register_user(req.email, req.password, req.full_name)
    return ApiResponse(data=user, trace_id=new_id("trc"))

@app.post("/api/v1/auth/login")
def login(req: UserLoginRequest):
    session = auth_service.login(req.email, req.password)
    return ApiResponse(data=session, trace_id=new_id("trc"))

# 3. Organization & Workspace APIs
@app.post("/api/v1/organizations")
def create_org(req: OrganizationCreateRequest, authorization: Optional[str] = Header(None)):
    token = _extract_bearer(authorization)
    payload = decode_jwt_token(token)
    org = org_service.create_organization(payload["sub"], req.name, req.slug, req.plan_tier)
    return ApiResponse(data=org, trace_id=new_id("trc"))

@app.get("/api/v1/organizations/{org_id}/workspaces")
def list_workspaces(org_id: str, authorization: Optional[str] = Header(None)):
    ctx = _require_context(authorization, org_id, "MEMBER")
    return ApiResponse(data=org_service.list_workspaces(ctx), trace_id=ctx.trace_id)

@app.post("/api/v1/organizations/{org_id}/workspaces")
def create_workspace(org_id: str, req: WorkspaceCreateRequest, authorization: Optional[str] = Header(None)):
    ctx = _require_context(authorization, org_id, "MANAGER")
    ws = org_service.create_workspace(ctx, req.name, req.description, req.access_level)
    return ApiResponse(data=ws, trace_id=ctx.trace_id)

@app.post("/api/v1/organizations/{org_id}/invitations")
def invite_member(org_id: str, req: InvitationCreateRequest, authorization: Optional[str] = Header(None)):
    ctx = _require_context(authorization, org_id, "ADMIN")
    res = org_service.add_or_invite_member(ctx, req.email, req.role)
    return ApiResponse(data=res, trace_id=ctx.trace_id)

@app.get("/api/v1/organizations/{org_id}/members")
def list_members(org_id: str, authorization: Optional[str] = Header(None)):
    ctx = _require_context(authorization, org_id, "MEMBER")
    return ApiResponse(data=org_service.list_members(ctx), trace_id=ctx.trace_id)

# 4. Document & Ingestion APIs
@app.post("/api/v1/documents/upload")
def upload_document(
    req: DocumentUploadRequest,
    authorization: Optional[str] = Header(None),
    x_organization_id: Optional[str] = Header(None),
    x_idempotency_key: Optional[str] = Header(None),
):
    ctx = _require_context(authorization, x_organization_id, "MEMBER")
    raw_bytes = base64.b64decode(req.content_base64) if req.content_base64 else None
    res = doc_service.upload_and_ingest_document(
        ctx=ctx,
        workspace_id=req.workspace_id,
        title=req.title,
        filename=req.filename,
        classification=req.classification,
        raw_bytes=raw_bytes,
        raw_text=req.raw_text,
        mime_type=req.mime_type,
        change_summary=req.change_summary,
        idempotency_key=x_idempotency_key,
    )
    return ApiResponse(data=res, trace_id=ctx.trace_id)

@app.get("/api/v1/documents")
def list_documents(
    workspace_id: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
    x_organization_id: Optional[str] = Header(None),
):
    ctx = _require_context(authorization, x_organization_id, "MEMBER")
    return ApiResponse(data=doc_service.list_documents(ctx, workspace_id), trace_id=ctx.trace_id)

@app.get("/api/v1/documents/{doc_id}")
def get_document(
    doc_id: str,
    authorization: Optional[str] = Header(None),
    x_organization_id: Optional[str] = Header(None),
):
    ctx = _require_context(authorization, x_organization_id, "MEMBER")
    doc = doc_service.get_document(ctx, doc_id)
    versions = doc_service.get_document_versions(ctx, doc_id)
    chunks = doc_service.get_document_chunks(ctx, doc_id)
    return ApiResponse(data={"document": doc, "versions": versions, "chunks": chunks}, trace_id=ctx.trace_id)

@app.delete("/api/v1/documents/{doc_id}")
def delete_document(
    doc_id: str,
    authorization: Optional[str] = Header(None),
    x_organization_id: Optional[str] = Header(None),
):
    ctx = _require_context(authorization, x_organization_id, "MANAGER")
    return ApiResponse(data=doc_service.delete_document(ctx, doc_id), trace_id=ctx.trace_id)

# 5. Advanced Hybrid RAG Retrieval APIs
@app.post("/api/v1/retrieval/search")
def hybrid_search(
    req: RetrievalQueryRequest,
    authorization: Optional[str] = Header(None),
    x_organization_id: Optional[str] = Header(None),
):
    ctx = _require_context(authorization, x_organization_id, "MEMBER")
    out = rag_engine.retrieve_and_answer(
        ctx=ctx,
        query=req.query,
        workspace_id=req.workspace_id,
        top_k=req.top_k,
        dense_weight=req.dense_weight,
        lexical_weight=req.lexical_weight,
        rerank=req.rerank,
        document_ids=req.document_ids,
        classification_filter=req.classification_filter,
    )
    return ApiResponse(data=out, trace_id=ctx.trace_id)

# 6. Conversations & Streaming APIs
@app.post("/api/v1/conversations")
def create_conversation(
    req: ConversationCreateRequest,
    authorization: Optional[str] = Header(None),
    x_organization_id: Optional[str] = Header(None),
):
    ctx = _require_context(authorization, x_organization_id, "MEMBER")
    return ApiResponse(data=conv_service.create_conversation(ctx, req.workspace_id, req.title), trace_id=ctx.trace_id)

@app.get("/api/v1/conversations")
def list_conversations(
    workspace_id: Optional[str] = Query(None),
    q: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
    x_organization_id: Optional[str] = Header(None),
):
    ctx = _require_context(authorization, x_organization_id, "MEMBER")
    return ApiResponse(data=conv_service.list_conversations(ctx, workspace_id, q), trace_id=ctx.trace_id)

@app.get("/api/v1/conversations/{conv_id}")
def get_conversation(
    conv_id: str,
    authorization: Optional[str] = Header(None),
    x_organization_id: Optional[str] = Header(None),
):
    ctx = _require_context(authorization, x_organization_id, "MEMBER")
    return ApiResponse(data=conv_service.get_conversation(ctx, conv_id), trace_id=ctx.trace_id)

@app.post("/api/v1/conversations/{conv_id}/messages")
def post_message(
    conv_id: str,
    req: MessageCreateRequest,
    authorization: Optional[str] = Header(None),
    x_organization_id: Optional[str] = Header(None),
):
    ctx = _require_context(authorization, x_organization_id, "MEMBER")
    return ApiResponse(data=conv_service.send_message(ctx, conv_id, req.content, req.top_k), trace_id=ctx.trace_id)

@app.post("/api/v1/conversations/{conv_id}/stream")
def stream_message(
    conv_id: str,
    req: MessageCreateRequest,
    authorization: Optional[str] = Header(None),
    x_organization_id: Optional[str] = Header(None),
):
    ctx = _require_context(authorization, x_organization_id, "MEMBER")
    return StreamingResponse(
        conv_service.stream_message(ctx, conv_id, req.content, req.top_k),
        media_type="text/event-stream",
    )

@app.post("/api/v1/conversations/messages/{msg_id}/feedback")
def submit_feedback(
    msg_id: str,
    req: FeedbackCreateRequest,
    authorization: Optional[str] = Header(None),
    x_organization_id: Optional[str] = Header(None),
):
    ctx = _require_context(authorization, x_organization_id, "MEMBER")
    return ApiResponse(data=conv_service.record_feedback(ctx, msg_id, req.rating, req.comment), trace_id=ctx.trace_id)

# 7. Multi-Agent Orchestration, Tool Registry & Approval APIs
@app.get("/api/v1/tools")
def list_registered_tools(
    authorization: Optional[str] = Header(None),
    x_organization_id: Optional[str] = Header(None),
):
    ctx = _require_context(authorization, x_organization_id, "MEMBER")
    return ApiResponse(data=tool_registry.list_tools(), trace_id=ctx.trace_id)

@app.post("/api/v1/agents/run")
def run_agent_workflow(
    req: AgentRunRequest,
    authorization: Optional[str] = Header(None),
    x_organization_id: Optional[str] = Header(None),
):
    ctx = _require_context(authorization, x_organization_id, "MEMBER")
    res = agent_orchestrator.start_workflow(
        ctx=ctx,
        workspace_id=req.workspace_id,
        query=req.query,
        conversation_id=req.conversation_id,
        parameters=req.parameters,
    )
    return ApiResponse(data=res, trace_id=ctx.trace_id)

@app.get("/api/v1/agents/runs")
def list_agent_runs(
    authorization: Optional[str] = Header(None),
    x_organization_id: Optional[str] = Header(None),
):
    ctx = _require_context(authorization, x_organization_id, "MEMBER")
    return ApiResponse(data=agent_orchestrator.list_runs(ctx), trace_id=ctx.trace_id)

@app.get("/api/v1/agents/runs/{run_id}")
def get_agent_run(
    run_id: str,
    authorization: Optional[str] = Header(None),
    x_organization_id: Optional[str] = Header(None),
):
    ctx = _require_context(authorization, x_organization_id, "MEMBER")
    return ApiResponse(data=agent_orchestrator.get_run_details(ctx, run_id), trace_id=ctx.trace_id)

@app.get("/api/v1/agents/approvals")
def list_approvals(
    authorization: Optional[str] = Header(None),
    x_organization_id: Optional[str] = Header(None),
):
    ctx = _require_context(authorization, x_organization_id, "MEMBER")
    return ApiResponse(data=agent_orchestrator.list_pending_approvals(ctx), trace_id=ctx.trace_id)

@app.post("/api/v1/agents/approvals/{approval_id}/decide")
def decide_approval(
    approval_id: str,
    req: ApprovalDecisionRequest,
    authorization: Optional[str] = Header(None),
    x_organization_id: Optional[str] = Header(None),
):
    ctx = _require_context(authorization, x_organization_id, "MANAGER")
    res = agent_orchestrator.resume_after_approval(ctx, approval_id, req.decision, req.review_note)
    return ApiResponse(data=res, trace_id=ctx.trace_id)

# 8. Data Analytics APIs
@app.get("/api/v1/analytics/datasets")
def list_datasets(
    workspace_id: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
    x_organization_id: Optional[str] = Header(None),
):
    ctx = _require_context(authorization, x_organization_id, "MEMBER")
    return ApiResponse(data=analytics_service.list_datasets(ctx, workspace_id), trace_id=ctx.trace_id)

@app.post("/api/v1/analytics/datasets/{dataset_id}/query")
def query_dataset(
    dataset_id: str,
    req: AnalyticsQueryRequest,
    authorization: Optional[str] = Header(None),
    x_organization_id: Optional[str] = Header(None),
):
    ctx = _require_context(authorization, x_organization_id, "MEMBER")
    res = analytics_service.run_analysis(
        ctx=ctx,
        dataset_id=dataset_id,
        operation=req.operation,
        group_by_column=req.group_by_column,
        metric_column=req.metric_column,
        agg_func=req.agg_func,
        filter_column=req.filter_column,
        filter_value=req.filter_value,
        date_column=req.date_column,
    )
    return ApiResponse(data=res, trace_id=ctx.trace_id)

# 9. Document Comparison & Report Center APIs
@app.post("/api/v1/reports/compare")
def compare_docs(
    req: DocumentComparisonRequest,
    authorization: Optional[str] = Header(None),
    x_organization_id: Optional[str] = Header(None),
):
    ctx = _require_context(authorization, x_organization_id, "MEMBER")
    res = report_service.compare_documents(
        ctx=ctx,
        doc_a_id=req.doc_a_id,
        doc_b_id=req.doc_b_id,
        version_a=req.version_a,
        version_b=req.version_b,
        report_title=req.report_title,
    )
    return ApiResponse(data=res, trace_id=ctx.trace_id)

# 10. Evaluation & Benchmarking APIs
@app.post("/api/v1/evaluation/runs")
def trigger_evaluation(
    authorization: Optional[str] = Header(None),
    x_organization_id: Optional[str] = Header(None),
):
    ctx = _require_context(authorization, x_organization_id, "MANAGER")
    res = eval_engine.run_benchmark_suite()
    return ApiResponse(data=res, trace_id=ctx.trace_id)

@app.get("/api/v1/evaluation/runs")
def list_evaluation_runs(
    authorization: Optional[str] = Header(None),
    x_organization_id: Optional[str] = Header(None),
):
    ctx = _require_context(authorization, x_organization_id, "MEMBER")
    return ApiResponse(data=eval_engine.list_runs(ctx), trace_id=ctx.trace_id)

# 11. Observability & Audit Log APIs
@app.get("/api/v1/observability/metrics")
def get_observability_dashboard(
    authorization: Optional[str] = Header(None),
    x_organization_id: Optional[str] = Header(None),
):
    ctx = _require_context(authorization, x_organization_id, "MEMBER")
    return ApiResponse(data=obs_service.get_dashboard_metrics(ctx.organization_id), trace_id=ctx.trace_id)

@app.get("/api/v1/audit/logs")
def get_audit_logs(
    limit: int = Query(100),
    authorization: Optional[str] = Header(None),
    x_organization_id: Optional[str] = Header(None),
):
    ctx = _require_context(authorization, x_organization_id, "ADMIN")
    return ApiResponse(data=audit_service.list_logs(ctx.organization_id, limit), trace_id=ctx.trace_id)
