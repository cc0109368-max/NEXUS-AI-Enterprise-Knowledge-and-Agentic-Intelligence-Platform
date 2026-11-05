from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

ROLE_HIERARCHY = {
    "MEMBER": 1,
    "MANAGER": 2,
    "ADMIN": 3,
    "OWNER": 4,
}

CLASSIFICATION_TO_MIN_ROLE = {
    "PUBLIC": "MEMBER",
    "INTERNAL": "MEMBER",
    "CONFIDENTIAL": "MANAGER",
    "RESTRICTED": "ADMIN",
}

class ApiResponse(BaseModel):
    success: bool = True
    data: Any = None
    meta: Dict[str, Any] = Field(default_factory=dict)
    trace_id: str = ""

class ApiError(BaseModel):
    success: bool = False
    error_code: str
    message: str
    details: Dict[str, Any] = Field(default_factory=dict)
    trace_id: str = ""

class UserRegisterRequest(BaseModel):
    email: str
    password: str
    full_name: str

class UserLoginRequest(BaseModel):
    email: str
    password: str

class OrganizationCreateRequest(BaseModel):
    name: str
    slug: str
    plan_tier: str = "ENTERPRISE"

class WorkspaceCreateRequest(BaseModel):
    name: str
    description: str = ""
    access_level: str = "ORG_WIDE"

class InvitationCreateRequest(BaseModel):
    email: str
    role: str = "MEMBER"

class DocumentUploadRequest(BaseModel):
    workspace_id: str
    title: str
    filename: str
    mime_type: str = "text/markdown"
    classification: str = "INTERNAL"
    content_base64: Optional[str] = None
    raw_text: Optional[str] = None
    change_summary: str = "Initial upload"

class RetrievalQueryRequest(BaseModel):
    workspace_id: Optional[str] = None
    query: str
    top_k: int = 5
    dense_weight: float = 0.55
    lexical_weight: float = 0.45
    rerank: bool = True
    document_ids: Optional[List[str]] = None
    classification_filter: Optional[str] = None

class ConversationCreateRequest(BaseModel):
    workspace_id: str
    title: str

class MessageCreateRequest(BaseModel):
    content: str
    top_k: int = 5

class FeedbackCreateRequest(BaseModel):
    rating: int
    comment: str = ""

class AgentRunRequest(BaseModel):
    workspace_id: str
    query: str
    conversation_id: Optional[str] = None
    parameters: Dict[str, Any] = Field(default_factory=dict)

class ApprovalDecisionRequest(BaseModel):
    decision: str  # APPROVED or REJECTED
    review_note: str = ""

class AnalyticsQueryRequest(BaseModel):
    operation: str  # describe, filter_aggregate, group_by, time_series
    group_by_column: Optional[str] = None
    metric_column: Optional[str] = None
    agg_func: str = "sum"
    filter_column: Optional[str] = None
    filter_value: Optional[Any] = None
    date_column: Optional[str] = None

class DocumentComparisonRequest(BaseModel):
    doc_a_id: str
    version_a: Optional[int] = None
    doc_b_id: str
    version_b: Optional[int] = None
    report_title: str = "Policy & Document Version Comparison Report"
