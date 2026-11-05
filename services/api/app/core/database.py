import json
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional
from .config import settings

_local = threading.local()

def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def new_id(prefix: str = "") -> str:
    uid = uuid.uuid4().hex[:16]
    return f"{prefix}_{uid}" if prefix else uid

SCHEMA_SQL = '''
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    full_name TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1,
    refresh_token_hash TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS organizations (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    slug TEXT UNIQUE NOT NULL,
    plan_tier TEXT NOT NULL DEFAULT 'ENTERPRISE',
    max_monthly_tokens INTEGER NOT NULL DEFAULT 10000000,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS organization_members (
    id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN ('OWNER', 'ADMIN', 'MANAGER', 'MEMBER')),
    joined_at TEXT NOT NULL,
    UNIQUE (organization_id, user_id)
);

CREATE TABLE IF NOT EXISTS workspaces (
    id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    access_level TEXT NOT NULL DEFAULT 'ORG_WIDE',
    created_by TEXT NOT NULL REFERENCES users(id),
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS invitations (
    id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    email TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('OWNER', 'ADMIN', 'MANAGER', 'MEMBER')),
    token_hash TEXT UNIQUE NOT NULL,
    status TEXT NOT NULL DEFAULT 'PENDING',
    expires_at TEXT NOT NULL,
    created_by TEXT NOT NULL REFERENCES users(id),
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    filename TEXT NOT NULL,
    mime_type TEXT NOT NULL,
    file_size_bytes INTEGER NOT NULL,
    sha256_hash TEXT NOT NULL,
    current_version INTEGER NOT NULL DEFAULT 1,
    classification TEXT NOT NULL DEFAULT 'INTERNAL' CHECK (classification IN ('PUBLIC', 'INTERNAL', 'CONFIDENTIAL', 'RESTRICTED')),
    min_role_required TEXT NOT NULL DEFAULT 'MEMBER' CHECK (min_role_required IN ('MEMBER', 'MANAGER', 'ADMIN', 'OWNER')),
    status TEXT NOT NULL DEFAULT 'PENDING',
    error_message TEXT,
    uploaded_by TEXT NOT NULL REFERENCES users(id),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS document_versions (
    id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    organization_id TEXT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    version_number INTEGER NOT NULL,
    sha256_hash TEXT NOT NULL,
    storage_path TEXT NOT NULL,
    page_count INTEGER NOT NULL DEFAULT 1,
    word_count INTEGER NOT NULL DEFAULT 0,
    parser_used TEXT NOT NULL,
    change_summary TEXT NOT NULL DEFAULT '',
    created_by TEXT NOT NULL REFERENCES users(id),
    created_at TEXT NOT NULL,
    UNIQUE (document_id, version_number)
);

CREATE TABLE IF NOT EXISTS document_chunks (
    id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    document_version_id TEXT NOT NULL REFERENCES document_versions(id) ON DELETE CASCADE,
    organization_id TEXT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL,
    page_number INTEGER NOT NULL DEFAULT 1,
    section_title TEXT NOT NULL DEFAULT 'General',
    content TEXT NOT NULL,
    token_count INTEGER NOT NULL,
    char_start INTEGER NOT NULL DEFAULT 0,
    char_end INTEGER NOT NULL DEFAULT 0,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    is_quarantined_injection INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE VIRTUAL TABLE IF NOT EXISTS document_chunks_fts USING fts5(
    chunk_id UNINDEXED,
    organization_id UNINDEXED,
    document_id UNINDEXED,
    section_title,
    content
);

CREATE TABLE IF NOT EXISTS document_embeddings (
    id TEXT PRIMARY KEY,
    chunk_id TEXT UNIQUE NOT NULL REFERENCES document_chunks(id) ON DELETE CASCADE,
    organization_id TEXT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    embedding_model TEXT NOT NULL DEFAULT 'gemini-embedding-001',
    dimensions INTEGER NOT NULL DEFAULT 128,
    vector_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ingestion_jobs (
    id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    document_version_id TEXT NOT NULL REFERENCES document_versions(id) ON DELETE CASCADE,
    idempotency_key TEXT UNIQUE NOT NULL,
    status TEXT NOT NULL DEFAULT 'QUEUED',
    attempt_count INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    error_message TEXT,
    started_at TEXT,
    completed_at TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    is_archived INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    organization_id TEXT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
    content TEXT NOT NULL,
    abstained INTEGER NOT NULL DEFAULT 0,
    abstention_reason TEXT,
    faithfulness_score REAL DEFAULT 1.0,
    prompt_tokens INTEGER NOT NULL DEFAULT 0,
    completion_tokens INTEGER NOT NULL DEFAULT 0,
    latency_ms REAL NOT NULL DEFAULT 0.0,
    trace_id TEXT,
    feedback_rating INTEGER,
    feedback_comment TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS citations (
    id TEXT PRIMARY KEY,
    message_id TEXT NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
    organization_id TEXT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    document_version_id TEXT NOT NULL REFERENCES document_versions(id) ON DELETE CASCADE,
    chunk_id TEXT NOT NULL REFERENCES document_chunks(id) ON DELETE CASCADE,
    citation_key TEXT NOT NULL,
    page_number INTEGER NOT NULL,
    section_title TEXT NOT NULL,
    excerpt TEXT NOT NULL,
    relevance_score REAL NOT NULL,
    verified INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS agent_runs (
    id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    conversation_id TEXT,
    intent TEXT NOT NULL,
    status TEXT NOT NULL,
    current_node TEXT NOT NULL,
    step_count INTEGER NOT NULL DEFAULT 0,
    max_steps INTEGER NOT NULL DEFAULT 12,
    input_query TEXT NOT NULL,
    final_output TEXT,
    error_message TEXT,
    trace_id TEXT NOT NULL,
    started_at TEXT NOT NULL,
    completed_at TEXT
);

CREATE TABLE IF NOT EXISTS agent_checkpoints (
    id TEXT PRIMARY KEY,
    agent_run_id TEXT REFERENCES agent_runs(id) ON DELETE CASCADE,
    organization_id TEXT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    step_number INTEGER NOT NULL,
    node_name TEXT NOT NULL,
    state_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tool_executions (
    id TEXT PRIMARY KEY,
    agent_run_id TEXT REFERENCES agent_runs(id) ON DELETE CASCADE,
    organization_id TEXT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    tool_name TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    arguments_json TEXT NOT NULL,
    result_json TEXT,
    status TEXT NOT NULL,
    duration_ms REAL NOT NULL DEFAULT 0.0,
    requires_approval INTEGER NOT NULL DEFAULT 0,
    approved_by TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS approval_requests (
    id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    agent_run_id TEXT REFERENCES agent_runs(id) ON DELETE CASCADE,
    tool_name TEXT NOT NULL,
    action_summary TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    requested_by TEXT NOT NULL REFERENCES users(id),
    status TEXT NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING', 'APPROVED', 'REJECTED')),
    reviewed_by TEXT REFERENCES users(id),
    review_note TEXT,
    created_at TEXT NOT NULL,
    resolved_at TEXT
);

CREATE TABLE IF NOT EXISTS datasets (
    id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    row_count INTEGER NOT NULL,
    column_count INTEGER NOT NULL,
    schema_json TEXT NOT NULL,
    summary_stats_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS evaluation_runs (
    id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    suite_name TEXT NOT NULL,
    dataset_version TEXT NOT NULL,
    total_cases INTEGER NOT NULL,
    passed_cases INTEGER NOT NULL,
    metrics_summary_json TEXT NOT NULL,
    status TEXT NOT NULL,
    duration_ms REAL NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS evaluation_cases (
    id TEXT PRIMARY KEY,
    category TEXT NOT NULL,
    query TEXT NOT NULL,
    expected_doc_ids_json TEXT NOT NULL,
    expected_answer_keywords_json TEXT NOT NULL,
    expect_abstention INTEGER NOT NULL DEFAULT 0,
    expect_security_block INTEGER NOT NULL DEFAULT 0,
    expected_tool TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS evaluation_results (
    id TEXT PRIMARY KEY,
    evaluation_run_id TEXT NOT NULL REFERENCES evaluation_runs(id) ON DELETE CASCADE,
    case_id TEXT NOT NULL REFERENCES evaluation_cases(id) ON DELETE CASCADE,
    passed INTEGER NOT NULL,
    recall_at_k REAL NOT NULL,
    precision_at_k REAL NOT NULL,
    mrr REAL NOT NULL,
    ndcg REAL NOT NULL,
    faithfulness REAL NOT NULL,
    citation_precision REAL NOT NULL,
    actual_output TEXT NOT NULL,
    latency_ms REAL NOT NULL,
    details_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS model_usage (
    id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    user_id TEXT NOT NULL REFERENCES users(id),
    trace_id TEXT NOT NULL,
    provider TEXT NOT NULL,
    model_name TEXT NOT NULL,
    operation_type TEXT NOT NULL,
    prompt_tokens INTEGER NOT NULL,
    completion_tokens INTEGER NOT NULL,
    total_tokens INTEGER NOT NULL,
    estimated_cost_usd REAL NOT NULL,
    latency_ms REAL NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_logs (
    id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL,
    actor_user_id TEXT,
    event_type TEXT NOT NULL,
    resource_type TEXT NOT NULL,
    resource_id TEXT,
    action TEXT NOT NULL,
    status TEXT NOT NULL,
    ip_address TEXT NOT NULL DEFAULT '127.0.0.1',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS internal_tasks (
    id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    priority TEXT NOT NULL DEFAULT 'HIGH',
    assignee_email TEXT,
    status TEXT NOT NULL DEFAULT 'OPEN',
    created_by_agent_run_id TEXT REFERENCES agent_runs(id),
    idempotency_key TEXT UNIQUE NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_docs_org ON documents(organization_id, workspace_id);
CREATE INDEX IF NOT EXISTS idx_chunks_org ON document_chunks(organization_id, document_id);
CREATE INDEX IF NOT EXISTS idx_emb_org ON document_embeddings(organization_id);
CREATE INDEX IF NOT EXISTS idx_audit_org ON audit_logs(organization_id, created_at);
'''

class DatabaseManager:
    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or settings.db_path
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _init_schema(self) -> None:
        conn = sqlite3.connect(self.db_path)
        try:
            conn.executescript(SCHEMA_SQL)
            conn.commit()
        finally:
            conn.close()

    @contextmanager
    def connection(self) -> Generator[sqlite3.Connection, None, None]:
        conn = sqlite3.connect(self.db_path, timeout=30.0, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def fetch_all(self, query: str, params: tuple = ()) -> List[Dict[str, Any]]:
        with self.connection() as conn:
            cur = conn.execute(query, params)
            return [dict(row) for row in cur.fetchall()]

    def fetch_one(self, query: str, params: tuple = ()) -> Optional[Dict[str, Any]]:
        with self.connection() as conn:
            cur = conn.execute(query, params)
            row = cur.fetchone()
            return dict(row) if row else None

    def execute(self, query: str, params: tuple = ()) -> int:
        with self.connection() as conn:
            cur = conn.execute(query, params)
            return cur.rowcount

db = DatabaseManager()
